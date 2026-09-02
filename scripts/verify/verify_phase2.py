"""Phase 2 verification: the dose loop, against the live database.

Runs the whole AGENTS.md Phase 2 gate except the actual WhatsApp delivery:
taken path, missed path, and the late-reply reclassification - plus the
idempotency guarantees that a restart never double-sends.

Outbound sends are captured instead of transmitted, so this needs no Meta
credentials.
"""

import asyncio, os, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# scripts/verify/<this file> -> scripts/verify -> scripts -> <repo root>
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)

from app.config import settings
settings.followup_minutes = 1
settings.escalate_minutes = 2

from fastapi.testclient import TestClient
from sqlmodel import select

from app.db import session_scope
from app.models import (Caretaker, DoseEvent, Family, Medicine, MessageLog,
                        Patient, Schedule)
from app.scheduler import state_machine as sm
from app.scheduler import ticker
from app.whatsapp import client as wa

PASS, FAIL = [], []
SENT = []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    mark = "PASS" if cond else "FAIL"
    print(f"  {mark}  {label}" + (f"   -> {detail}" if detail and not cond else ""))


# ---- capture outbound instead of sending -------------------------------
async def fake_template(to, template, lang, body_vars=None, button_payloads=None):
    SENT.append({"kind": "template", "to": to, "template": template,
                 "vars": body_vars, "payloads": button_payloads})
    return f"wamid.FAKE.{len(SENT)}"


async def fake_text(to, body):
    SENT.append({"kind": "text", "to": to, "body": body})
    return f"wamid.FAKE.{len(SENT)}"


wa.send_template = fake_template
wa.send_text = fake_text

PNUM, CNUM = "923001110001", "923002220002"


def cleanup():
    with session_scope() as s:
        pat = s.exec(select(Patient).where(Patient.whatsapp_number == PNUM)).first()
        if pat:
            for row in s.exec(select(MessageLog).where(MessageLog.patient_id == pat.id)).all():
                s.delete(row)
            for d in s.exec(select(DoseEvent).where(DoseEvent.patient_id == pat.id)).all():
                s.delete(d)
            s.commit()
            for m in s.exec(select(Medicine).where(Medicine.patient_id == pat.id)).all():
                for sc in s.exec(select(Schedule).where(Schedule.medicine_id == m.id)).all():
                    s.delete(sc)
                s.commit()
                s.delete(m)
            s.commit()
            fam_id = pat.family_id
            s.delete(pat); s.commit()
        else:
            fam_id = None
        for c in s.exec(select(Caretaker).where(Caretaker.phone == CNUM)).all():
            fam_id = fam_id or c.family_id
            s.delete(c)
        s.commit()
        for f in s.exec(select(Family).where(Family.name == "PHASE2 VERIFY")).all():
            for ml in s.exec(select(MessageLog).where(MessageLog.caretaker_id.is_(None))).all():
                pass
            s.delete(f)
        s.commit()


def seed(dose_times, minutes_ago=0):
    """Build a family with one medicine whose dose was due `minutes_ago`."""
    with session_scope() as s:
        fam = Family(name="PHASE2 VERIFY"); s.add(fam); s.commit(); s.refresh(fam)
        care = Caretaker(family_id=fam.id, name="Zakir", phone=CNUM,
                         relation="beta", verified=True)
        pat = Patient(family_id=fam.id, name="Ammi", whatsapp_number=PNUM,
                      language="ur", opted_in=True)
        s.add(care); s.add(pat); s.commit(); s.refresh(care); s.refresh(pat)
        med = Medicine(patient_id=pat.id, name="Panadol", strength="500mg")
        s.add(med); s.commit(); s.refresh(med)
        sch = Schedule(medicine_id=med.id, dose_times=dose_times, duration_days=7,
                       start_date=date.today(), end_date=date.today() + timedelta(days=6))
        s.add(sch); s.commit(); s.refresh(sch)
        return fam.id, pat.id, care.id, med.id, sch.id


def make_dose(sch_id, pat_id, when):
    with session_scope() as s:
        d = DoseEvent(schedule_id=sch_id, patient_id=pat_id, scheduled_at=when,
                      idempotency_key=f"{sch_id}:{when.isoformat()}", state="SCHEDULED")
        s.add(d); s.commit(); s.refresh(d)
        return d.id


def state_of(dose_id):
    with session_scope() as s:
        d = s.get(DoseEvent, dose_id)
        return d.state if d else None


def backdate(dose_id, minutes):
    with session_scope() as s:
        d = s.get(DoseEvent, dose_id)
        d.sent_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        s.add(d); s.commit()


async def main():
    cleanup()
    print("\n=== A. materialisation is idempotent (invariant 5)")
    fam, pat, care, med, sch = seed(["08:00", "20:00"])
    n1 = ticker.materialise_doses(hours_ahead=24)
    n2 = ticker.materialise_doses(hours_ahead=24)
    n3 = ticker.materialise_doses(hours_ahead=24)
    check(f"first run created {n1} doses", n1 > 0, n1)
    check("second run creates 0 (ON CONFLICT DO NOTHING)", n2 == 0, n2)
    check("third run creates 0 - a restart never duplicates", n3 == 0, n3)

    with session_scope() as s:
        keys = [d.idempotency_key for d in
                s.exec(select(DoseEvent).where(DoseEvent.patient_id == pat)).all()]
    check("every idempotency_key is unique", len(keys) == len(set(keys)), keys)

    print("\n=== B. end_date is INCLUSIVE (SCHEMA.md)")
    with session_scope() as s:
        sc = s.get(Schedule, sch)
        span = (sc.end_date - sc.start_date).days + 1
    check(f"7-day course spans exactly 7 calendar days (got {span})", span == 7, span)

    print("\n=== C. TAKEN path: reminder -> button tap -> TAKEN")
    SENT.clear()
    now = datetime.now(timezone.utc)
    d1 = make_dose(sch, pat, now - timedelta(seconds=30))
    counts = await ticker.tick()
    check("reminder fired", counts["reminded"] == 1, counts)
    check("state is AWAITING_REPLY", state_of(d1) == "AWAITING_REPLY", state_of(d1))
    tmpl = [m for m in SENT if m.get("template") == "dose_reminder"]
    check("dose_reminder template used (invariant 1)", len(tmpl) == 1, SENT)
    check("sent to the patient", tmpl and tmpl[0]["to"] == PNUM, tmpl)
    check("medicine name AND strength in the copy (section 11)",
          tmpl and "Panadol 500mg" in tmpl[0]["vars"], tmpl)
    check("button payloads carry the dose id (invariant 2)",
          tmpl and tmpl[0]["payloads"] == [f"TAKEN:{d1}", f"LATER:{d1}"], tmpl)

    landed = sm.confirm_taken(d1, "button", "Le li")
    check("button tap -> TAKEN", landed == "TAKEN" and state_of(d1) == "TAKEN", landed)

    SENT.clear()
    await ticker.tick()
    check("escalation chain cancelled - no further sends", len(SENT) == 0, SENT)

    print("\n=== D. MISSED path: silence -> follow-up -> caretaker alert")
    SENT.clear()
    d2 = make_dose(sch, pat, datetime.now(timezone.utc) - timedelta(seconds=30))
    await ticker.tick()
    check("reminder sent", state_of(d2) == "AWAITING_REPLY", state_of(d2))

    backdate(d2, settings.followup_minutes + 0.5)
    SENT.clear()
    c = await ticker.tick()
    check("follow-up fired after FOLLOWUP_MINUTES", c["followed_up"] == 1, c)
    check("state is REMINDED_AGAIN", state_of(d2) == "REMINDED_AGAIN", state_of(d2))
    check("dose_followup template used",
          any(m.get("template") == "dose_followup" for m in SENT), SENT)

    backdate(d2, settings.escalate_minutes + 0.5)
    SENT.clear()
    c = await ticker.tick()
    check("escalated after ESCALATE_MINUTES", c["escalated"] == 1, c)
    check("state is MISSED", state_of(d2) == "MISSED", state_of(d2))
    alert = [m for m in SENT if m.get("template") == "caretaker_alert"]
    check("caretaker_alert template used", len(alert) == 1, SENT)
    check("sent to the CARETAKER, not the patient",
          alert and alert[0]["to"] == CNUM, alert)
    with session_scope() as s:
        check("caretaker_alerted_at recorded", s.get(DoseEvent, d2).caretaker_alerted_at is not None)

    SENT.clear()
    await ticker.tick()
    check("caretaker is not alerted twice", len(SENT) == 0, SENT)

    print("\n=== E. LATE reply reclassifies MISSED -> TAKEN_LATE (section 4.8)")
    SENT.clear()
    landed = sm.confirm_taken(d2, "text", "sorry, abhi li hai")
    check("MISSED -> TAKEN_LATE", landed == "TAKEN_LATE" and state_of(d2) == "TAKEN_LATE", landed)
    await ticker.notify_late_resolution(d2)
    notes = [m for m in SENT if m["kind"] == "text"]
    check("caretaker told it resolved", len(notes) == 1 and notes[0]["to"] == CNUM, SENT)
    check("resolution message is free-form, not a template",
          notes and "tasdeeq" in notes[0]["body"], notes)
    with session_scope() as s:
        check("patient's own words kept verbatim (for the doctor PDF)",
              s.get(DoseEvent, d2).response_text == "sorry, abhi li hai")

    print("\n=== F. illegal transitions are refused, not silently applied")
    check("TAKEN cannot go back to REMINDED_AGAIN", sm.mark_reminded_again(d1) is False)
    check("TAKEN cannot become MISSED", sm.mark_missed(d1) is False)
    check("state unchanged after refusals", state_of(d1) == "TAKEN", state_of(d1))
    check("TAKEN_LATE is terminal", sm.mark_missed(d2) is False)

    print("\n=== G. a restart never re-sends (invariant 5)")
    SENT.clear()
    d3 = make_dose(sch, pat, datetime.now(timezone.utc) - timedelta(seconds=30))
    await ticker.tick()
    first = len(SENT)
    await ticker.tick()          # simulates the process restarting and ticking again
    await ticker.tick()
    check(f"reminder sent exactly once across 3 ticks (got {len(SENT)})",
          len(SENT) == first == 1, len(SENT))

    print("\n=== H. a dose that went stale while we were down is not blasted out")
    SENT.clear()
    old = datetime.now(timezone.utc) - timedelta(hours=3)
    d4 = make_dose(sch, pat, old)
    c = await ticker.tick()
    check("stale dose marked MISSED without a reminder", state_of(d4) == "MISSED", state_of(d4))
    check("no stale reminder sent to the patient",
          not any(m.get("template") == "dose_reminder" for m in SENT), SENT)

    print("\n=== I. button tap through the real webhook (end to end)")
    client = TestClient(__import__("app.main", fromlist=["app"]).app)
    SENT.clear()
    d5 = make_dose(sch, pat, datetime.now(timezone.utc) - timedelta(seconds=30))
    await ticker.tick()
    check("dose awaiting reply", state_of(d5) == "AWAITING_REPLY", state_of(d5))

    body = {"id": "wamid.P2.BTN", "from": PNUM, "timestamp": 1755870000,
            "type": "button", "buttonId": f"TAKEN:{d5}", "text": "Le li"}
    r = client.post(f"/webhook/{settings.webhook_secret}", json=body)
    check("webhook returned 200", r.status_code == 200, r.status_code)
    check("button tap moved the dose to TAKEN", state_of(d5) == "TAKEN", state_of(d5))
    with session_scope() as s:
        row = s.exec(select(MessageLog).where(
            MessageLog.wa_message_id == "wamid.P2.BTN")).first()
        check("message_log links the reply to the dose",
              row and row.dose_event_id == d5, row.dose_event_id if row else None)
        check("response_source recorded as button",
              s.get(DoseEvent, d5).response_source == "button")

    print("\n=== J. 'Abhi nahi' is not a snooze - the chain keeps running")
    d6 = make_dose(sch, pat, datetime.now(timezone.utc) - timedelta(seconds=30))
    await ticker.tick()
    client.post(f"/webhook/{settings.webhook_secret}",
                json={"id": "wamid.P2.LATER", "from": PNUM, "timestamp": 1755870001,
                      "type": "button", "buttonId": f"LATER:{d6}", "text": "Abhi nahi"})
    check("state still open after 'abhi nahi'",
          state_of(d6) == "AWAITING_REPLY", state_of(d6))
    with session_scope() as s:
        check("reason recorded for the report", s.get(DoseEvent, d6).reason == "Abhi nahi")
    backdate(d6, settings.followup_minutes + 0.5)
    c = await ticker.tick()
    check("follow-up still fires after 'abhi nahi'", c["followed_up"] == 1, c)

    print("\n=== K. cleanup")
    cleanup()
    print("  test rows removed")

    print(f"\n{'=' * 62}\n  {len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print(f"    FAILED: {f}")
    return 1 if FAIL else 0


sys.exit(asyncio.run(main()))
