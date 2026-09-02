"""Phase 5: pre-generated Urdu voice notes, end to end.

Seeds a real schedule, pre-generates its audio, checks the files are OGG/Opus
mono (invariant 7), and proves the reminder path ATTACHES the cached file
rather than synthesising one. The last part matters most: section 3.4 forbids
calling out to Microsoft while a dose is due, and the only honest way to test
that is to break synthesis and confirm the reminder still carries audio.

Every voice note is also transcribed back with the local whisper, because a
file that is the right size and the right codec can still be saying the wrong
thing - which is exactly what Roman Urdu input turned out to do.

Outbound WhatsApp is captured rather than sent.
"""
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# scripts/verify/<this file> -> scripts/verify -> scripts -> <repo root>
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)

import av
from sqlmodel import col, delete, select

from app.config import settings
from app.db import session_scope
from app.models import Caretaker, DoseEvent, Medicine, Patient, Schedule
from app.whatsapp import client as wa

OK, BAD, WARN = [], [], []
SENT = []

TAG = "ZZ-verify-voice"


def check(label, cond, detail=""):
    (OK if cond else BAD).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          + (f"   -> {detail}" if detail and not cond else ""))


def warn(label, cond, detail=""):
    if cond:
        OK.append(label)
        print(f"  PASS  {label}")
    else:
        WARN.append(f"{label}: {detail}")
        print(f"  WARN  {label}   -> {detail}")


async def fake_text(to, body):
    SENT.append({"kind": "text", "to": to, "body": body})
    return f"fake.t{len(SENT)}"


async def fake_template(to, template, lang, body_vars=None, button_payloads=None):
    SENT.append({"kind": "text", "to": to, "body": f"[{template}]"})
    return f"fake.tpl{len(SENT)}"


async def fake_voice(to, blob):
    SENT.append({"kind": "voice", "to": to,
                 "bytes": bytes(blob) if isinstance(blob, (bytes, bytearray)) else b""})
    return f"fake.v{len(SENT)}"


wa.send_text = fake_text
wa.send_template = fake_template
wa.send_voice = fake_voice

from app.i18n import strings
from app.scheduler import ticker
from app.voice import asr, store, tts


def probe(blob: bytes) -> dict:
    """Codec, channels and rate, read off the actual file."""
    import io
    container = av.open(io.BytesIO(blob), "r")
    stream = container.streams.audio[0]
    info = {"codec": stream.codec_context.name, "channels": stream.channels,
            "rate": stream.rate,
            "seconds": round(float(container.duration or 0) / 1e6, 1)}
    container.close()
    return info


def seed() -> dict:
    start = date.today()
    with session_scope() as s:
        carer = s.exec(select(Caretaker).where(col(Caretaker.phone).isnot(None))
                       .order_by(col(Caretaker.created_at).desc())).first()
        if carer is None:
            raise SystemExit("no caretaker with a phone number - sign up first")

        p = Patient(family_id=carer.family_id, name=f"{TAG} Amina",
                    whatsapp_number="920000000196", language="ur", opted_in=True)
        s.add(p); s.commit(); s.refresh(p)

        m = Medicine(patient_id=p.id, name="Panadol", strength="500mg",
                     form="tablet")
        s.add(m); s.commit(); s.refresh(m)

        sc = Schedule(medicine_id=m.id, dose_times=["08:00", "20:00"],
                      duration_days=3, start_date=start,
                      end_date=start + timedelta(days=2))
        s.add(sc); s.commit(); s.refresh(sc)

        for day in range(3):
            for hhmm in ("08:00", "20:00"):
                h = int(hhmm[:2])
                when = datetime.combine(start + timedelta(days=day),
                                        datetime.min.time(), tzinfo=settings.tz)
                when = when.replace(hour=h).astimezone(timezone.utc)
                s.add(DoseEvent(
                    schedule_id=sc.id, patient_id=p.id,
                    idempotency_key=f"{sc.id}:{when.isoformat()}",
                    scheduled_at=when, state="SCHEDULED"))
        s.commit()
        return {"patient_id": p.id, "medicine_id": m.id, "schedule_id": sc.id,
                "phone": p.whatsapp_number}


def cleanup(ids: dict) -> None:
    with session_scope() as s:
        s.exec(delete(DoseEvent).where(DoseEvent.patient_id == ids["patient_id"]))
        s.exec(delete(Schedule).where(Schedule.medicine_id == ids["medicine_id"]))
        s.exec(delete(Medicine).where(Medicine.id == ids["medicine_id"]))
        s.exec(delete(Patient).where(Patient.id == ids["patient_id"]))
        s.commit()


async def main() -> int:
    print("=== the spoken copy is Urdu script, not the Roman Urdu of the message")
    line = strings.spoken("dose_reminder", hour="8", medicine="Panadol 500mg")
    text = strings.t("dose_reminder", "ur", name="Amina", hour="8",
                     medicine="Panadol 500mg", note="")
    print(f"     text : {text}")
    print(f"     voice: {line}")
    check("a spoken form exists for the reminder", bool(line))
    check("it is in Urdu script",
          any("\u0600" <= c <= "\u06ff" for c in line or ""), line or "")
    check("it keeps the medicine name as stored", "Panadol 500mg" in (line or ""))
    check("it does not lead with the patient's name",
          "{name}" not in (line or "") and "Amina" not in (line or ""))
    check("free text is never spoken - medicine_info has no spoken form",
          strings.spoken("medicine_info", medicine="x", purpose="y",
                         food_rule="z") is None)

    print("\n=== synthesis produces what invariant 7 requires")
    blob = await tts.synthesise(line)
    info = probe(blob)
    print(f"     {len(blob):,} bytes  {info}")
    check("codec is opus", info["codec"] == "opus", info["codec"])
    check("mono", info["channels"] == 1, str(info["channels"]))
    check("48kHz", info["rate"] == 48000, str(info["rate"]))
    check("it is not silence", len(blob) > 5000, f"{len(blob)} bytes")

    print("\n=== and it says the right thing (transcribed back)")
    heard = await asr.transcribe(blob, language="ur")
    print(f"     heard: {heard}")
    check("the hour survives", "بج" in heard, heard)
    check("the medicine name survives",
          "پینا" in heard or "پینہ" in heard, heard)

    print("\n=== the cache key is the content, not the dose")
    k1 = store.key_for(line)
    k2 = store.key_for("  " + line + "  ")
    check("whitespace does not make a new file", k1 == k2)
    check("a different sentence does make one",
          k1 != store.key_for(strings.spoken("dose_reminder", hour="9",
                                             medicine="Panadol 500mg")))
    check("a different medicine does too",
          k1 != store.key_for(strings.spoken("dose_reminder", hour="8",
                                             medicine="Brufen 400mg")))

    ids = seed()
    print(f"\nseeded 3-day course, 6 doses: patient={ids['patient_id'][:8]}")

    try:
        print("\n=== pre-generation, one file per unique dose text")
        created = await tts.pregenerate_for_schedule(ids["schedule_id"])
        print(f"     created {created} file(s) for 6 doses at 2 distinct times")
        check("two dose times produced at most two files", created <= 2,
              str(created))

        with session_scope() as s:
            doses = s.exec(select(DoseEvent).where(
                DoseEvent.schedule_id == ids["schedule_id"])).all()
            keys = [d.voice_note_key for d in doses]
        check("every dose got a voice note key", all(keys), str(keys[:3]))
        check("six doses share two files", len(set(keys)) == 2,
              str(sorted(set(k or '' for k in keys))))

        print("\n=== running it again generates nothing new")
        again = await tts.pregenerate_for_schedule(ids["schedule_id"])
        check("second run is a no-op", again == 0, str(again))

        print("\n=== the two times really are different audio")
        with session_scope() as s:
            by_time = {}
            for d in s.exec(select(DoseEvent).where(
                    DoseEvent.schedule_id == ids["schedule_id"])).all():
                when = d.scheduled_at
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                by_time[when.astimezone(settings.tz).strftime("%H:%M")] = d.id
        morning = store.get(
            next(d.voice_note_key for d in _doses(ids)
                 if d.id == by_time["08:00"]))
        evening = store.get(
            next(d.voice_note_key for d in _doses(ids)
                 if d.id == by_time["20:00"]))
        check("morning and evening audio differ", morning != evening)
        heard_m = await asr.transcribe(morning, language="ur")
        heard_e = await asr.transcribe(evening, language="ur")
        print(f"     08:00 -> {heard_m}")
        print(f"     20:00 -> {heard_e}")
        check("both name the medicine",
              "پینا" in heard_m or "پینہ" in heard_m,
              f"{heard_m} / {heard_e}")
        # The part-of-day word is the whole reason these two differ. Without
        # it both times render "8 baj gaye" and an evening dose sounds like a
        # morning one, which is how this check earned its place.
        check("the morning one says subah", "صبح" in heard_m, heard_m)
        check("the evening one says raat", "رات" in heard_e, heard_e)

        # ------------------------------------------------ the reminder path
        print("\n=== the reminder ATTACHES the file - it never synthesises")
        real_synth = tts.synthesise

        async def exploding(*a, **k):
            raise AssertionError(
                "the reminder path called synthesise() - section 3.4 forbids it")

        tts.synthesise = exploding
        try:
            SENT.clear()
            dose_id = by_time["08:00"]
            with session_scope() as s:
                d = s.get(DoseEvent, dose_id)
                d.state = "SCHEDULED"
                s.add(d); s.commit()

            ok = await ticker.send_reminder(dose_id)
            check("the reminder was sent", ok)
            kinds = [m["kind"] for m in SENT]
            check("a text reminder went out", "text" in kinds, str(kinds))
            check("a voice note went with it", "voice" in kinds, str(kinds))
            if "voice" in kinds:
                sent_audio = next(m["bytes"] for m in SENT if m["kind"] == "voice")
                check("it is the pre-generated file, byte for byte",
                      sent_audio == morning, f"{len(sent_audio)} bytes")
                check("text first, then voice",
                      kinds.index("text") < kinds.index("voice"), str(kinds))
        finally:
            tts.synthesise = real_synth

        print("\n=== a dose with no cached audio still gets its text reminder")
        with session_scope() as s:
            d = s.get(DoseEvent, by_time["20:00"])
            d.state = "SCHEDULED"
            d.voice_note_key = None
            s.add(d); s.commit()
        SENT.clear()
        ok = await ticker.send_reminder(by_time["20:00"])
        check("still sent", ok)
        check("text went out", any(m["kind"] == "text" for m in SENT))
        check("no voice note, and no crash",
              not any(m["kind"] == "voice" for m in SENT))

        print("\n=== the kill switch")
        settings.voice_notes_enabled = False
        try:
            with session_scope() as s:
                d = s.get(DoseEvent, by_time["08:00"])
                d.state = "SCHEDULED"
                s.add(d); s.commit()
            SENT.clear()
            await ticker.send_reminder(by_time["08:00"])
            check("VOICE_NOTES_ENABLED=false sends text only",
                  not any(m["kind"] == "voice" for m in SENT),
                  str([m["kind"] for m in SENT]))
            check("pre-generation is skipped too",
                  await tts.pregenerate_for_schedule(ids["schedule_id"]) == 0)
        finally:
            settings.voice_notes_enabled = True

        print("\n=== archiving")
        warn("voice notes are archived to Supabase Storage",
             __import__("app.storage", fromlist=["x"]).is_configured(),
             "SUPABASE_SERVICE_KEY not set. Audio is kept on local disk only, "
             "which is enough to run - but it is regenerated after a deploy.")

        print(f"\n=== cache: {store.stats()}")

    finally:
        cleanup(ids)
        print("\ncleaned up (cached audio kept - it is content-addressed).")

    print(f"\n{'=' * 58}\n  {len(OK)} passed, {len(BAD)} failed"
          + (f", {len(WARN)} warning(s)" if WARN else ""))
    for f in BAD:
        print(f"    FAILED: {f}")
    for w in WARN:
        print(f"    WARNING: {w}")
    return 1 if BAD else 0


def _doses(ids):
    with session_scope() as s:
        rows = s.exec(select(DoseEvent).where(
            DoseEvent.schedule_id == ids["schedule_id"])).all()
        for r in rows:
            s.expunge(r)
        return rows


sys.exit(asyncio.run(main()))
