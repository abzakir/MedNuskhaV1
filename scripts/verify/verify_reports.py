"""Phase 6: both PDFs, the on-demand endpoint and the daily course-end job.

Seeds a real 14-day course into the live database - taken, late, missed and
declined doses, Urdu reasons, two symptoms - then proves the reports describe
it correctly, that the share link works and that the course-end job fires once
and only once. Everything it creates is deleted at the end.

Outbound WhatsApp is captured rather than sent, so this does not message a
real phone.
"""
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\ASUS\Desktop\MedNuskha")
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)

from sqlmodel import col, delete, select

from app.config import settings
from app.db import session_scope
from app.models import (Caretaker, DoseEvent, Medicine, Patient, Report,
                        Schedule, SymptomReport)
from app.whatsapp import client as wa

OK, BAD, WARN = [], [], []
SENT = []

OUT = ROOT / "scripts" / "verify" / "_out"


def check(label, cond, detail=""):
    (OK if cond else BAD).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          + (f"   -> {detail}" if detail and not cond else ""))


def warn(label, cond, detail=""):
    """A gap in the environment, not a broken product. Visible, not fatal."""
    if cond:
        OK.append(label)
        print(f"  PASS  {label}")
    else:
        WARN.append(f"{label}: {detail}")
        print(f"  WARN  {label}   -> {detail}")


async def fake_text(to, body):
    SENT.append({"to": to, "body": body})
    return f"fake.{len(SENT)}"


wa.send_text = fake_text

from app.reports import caretaker_pdf, data, doctor_pdf
from app.reports import pdf as pdfdoc
from app.reports import service, storage
from app.scheduler import ticker

# Reading a PDF back needs a real extractor. fpdf2 subsets the bundled TTFs,
# so the content stream holds GLYPH IDS, not characters - grepping the bytes
# for a sentence finds nothing whether or not the sentence is on the page,
# which is exactly how an earlier version of this script "failed" on a
# disclaimer that was present all along. Uncompressing does not help either.
#
# pypdfium2 maps glyphs back through the font's ToUnicode table. It is a
# single pure wheel with no system dependencies, but it belongs to this
# script rather than to the product, so it is optional:
#     backend\.venv\Scripts\python.exe -m pip install pypdfium2
try:
    import pypdfium2

    def page_text(blob: bytes) -> str:
        """All the text, with line wrapping flattened.

        A sentence that happens to wrap is still the same sentence, and a
        check that misses it because of where the line broke is testing the
        layout engine rather than the copy.
        """
        path = OUT / "_extract.pdf"
        path.write_bytes(blob)
        doc = pypdfium2.PdfDocument(str(path))
        raw = "\n".join(p.get_textpage().get_text_range() for p in doc)
        return " ".join(raw.split())

    def page_count(blob: bytes) -> int:
        path = OUT / "_extract.pdf"
        path.write_bytes(blob)
        return len(pypdfium2.PdfDocument(str(path)))

except ImportError:  # pragma: no cover - the checks below downgrade to warnings
    pypdfium2 = None
    page_text = page_count = None

# --------------------------------------------------------------------------
# a 14-day course, built to exercise every branch of the report
# --------------------------------------------------------------------------

TAG = "ZZ-verify-reports"
START = date.today() - timedelta(days=14)
END = START + timedelta(days=13)          # end_date is INCLUSIVE
TIMES = ["08:00", "20:00"]

#: (day offset, time, state, response_text, reason)
PLAN = [
    (0, "08:00", "TAKEN", "haan le li", None),
    (0, "20:00", "TAKEN", "le li hai", None),
    (1, "08:00", "TAKEN", "ji han", None),
    (1, "20:00", "TAKEN_LATE", "abhi li hai", None),
    (2, "08:00", "TAKEN", "le li", None),
    (2, "20:00", "MISSED", "ابھی نہیں، بعد میں لوں گی", "ابھی نہیں، بعد میں لوں گی"),
    (3, "08:00", "TAKEN", "haan", None),
    (3, "20:00", "TAKEN", "le li hai", None),
    (4, "08:00", "MISSED", "گولی ختم ہو گئی ہے", "گولی ختم ہو گئی ہے"),
    (4, "20:00", "TAKEN", "le li", None),
    (5, "08:00", "TAKEN", "ji", None),
    (5, "20:00", "TAKEN", "haan le li", None),
    (6, "08:00", "TAKEN", "le li hai", None),
    (6, "20:00", "MISSED", None, None),
    (7, "08:00", "TAKEN", "haan", None),
    (7, "20:00", "TAKEN", "le li", None),
    (8, "08:00", "TAKEN", "ji han", None),
    (8, "20:00", "TAKEN_LATE", "der ho gayi, ab li hai", None),
    (9, "08:00", "TAKEN", "le li", None),
    (9, "20:00", "SKIPPED", "aaj tabiyat theek hai, nahi leni",
     "aaj tabiyat theek hai, nahi leni"),
    (10, "08:00", "TAKEN", "haan", None),
    (10, "20:00", "TAKEN", "le li hai", None),
    (11, "08:00", "TAKEN", "ji", None),
    (11, "20:00", "MISSED", "so gayi thi, yaad hi nahi raha",
     "so gayi thi, yaad hi nahi raha"),
    (12, "08:00", "TAKEN", "le li", None),
    (12, "20:00", "TAKEN", "haan le li", None),
    (13, "08:00", "TAKEN", "ji han", None),
    (13, "20:00", "TAKEN", "le li hai", None),
]

SYMPTOMS = [
    (4, "21:10", "سینے میں درد ہو رہا ہے", "emergency"),
    (8, "09:30", "thora sar chakra raha hai subah se", "routine"),
]

EXPECT_TAKEN = sum(1 for r in PLAN if r[2] in ("TAKEN", "TAKEN_LATE"))
EXPECT_ON_TIME = sum(1 for r in PLAN if r[2] == "TAKEN")
EXPECT_LATE = sum(1 for r in PLAN if r[2] == "TAKEN_LATE")
EXPECT_MISSED = sum(1 for r in PLAN if r[2] == "MISSED")
EXPECT_SKIPPED = sum(1 for r in PLAN if r[2] == "SKIPPED")
EXPECT_DECIDED = len(PLAN)


def utc(day_offset: int, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    local = datetime.combine(START + timedelta(days=day_offset),
                             datetime.min.time(), tzinfo=settings.tz)
    return local.replace(hour=h, minute=m).astimezone(timezone.utc)


def seed() -> dict:
    """Create the patient, medicine, schedule and every dose. Returns ids."""
    with session_scope() as s:
        carer = s.exec(select(Caretaker).where(col(Caretaker.phone).isnot(None))
                       .order_by(col(Caretaker.created_at).desc())).first()
        if carer is None:
            raise SystemExit("no caretaker with a phone number - sign up first")

        patient = Patient(family_id=carer.family_id, name=f"{TAG} Zubaida",
                          whatsapp_number="920000000199", language="ur",
                          opted_in=True)
        s.add(patient)
        s.commit()
        s.refresh(patient)

        medicine = Medicine(patient_id=patient.id, name=f"{TAG} Panadol",
                            strength="500mg", form="tablet")
        s.add(medicine)
        s.commit()
        s.refresh(medicine)

        schedule = Schedule(medicine_id=medicine.id, dose_times=TIMES,
                            duration_days=14, start_date=START, end_date=END)
        s.add(schedule)
        s.commit()
        s.refresh(schedule)

        dose_ids = {}
        for day, hhmm, state, said, reason in PLAN:
            when = utc(day, hhmm)
            dose = DoseEvent(
                schedule_id=schedule.id, patient_id=patient.id,
                idempotency_key=f"{schedule.id}:{when.isoformat()}",
                scheduled_at=when, state=state,
                sent_at=when, responded_at=when + timedelta(minutes=4),
                response_source="text", response_text=said, reason=reason,
            )
            s.add(dose)
            dose_ids[(day, hhmm)] = dose
        s.commit()

        for day, hhmm, text, severity in SYMPTOMS:
            s.add(SymptomReport(
                patient_id=patient.id,
                dose_event_id=dose_ids[(day, "08:00" if hhmm < "12:00" else "20:00")].id,
                text_verbatim=text, language="ur", severity=severity,
                reported_at=utc(day, hhmm)))
        s.commit()

        return {"patient_id": patient.id, "medicine_id": medicine.id,
                "schedule_id": schedule.id, "carer_phone": carer.phone,
                "family_id": carer.family_id}


def cleanup(ids: dict) -> None:
    with session_scope() as s:
        s.exec(delete(Report).where(Report.patient_id == ids["patient_id"]))
        s.exec(delete(SymptomReport).where(
            SymptomReport.patient_id == ids["patient_id"]))
        s.exec(delete(DoseEvent).where(DoseEvent.patient_id == ids["patient_id"]))
        s.exec(delete(Schedule).where(Schedule.medicine_id == ids["medicine_id"]))
        s.exec(delete(Medicine).where(Medicine.id == ids["medicine_id"]))
        s.exec(delete(Patient).where(Patient.id == ids["patient_id"]))
        s.commit()


async def main() -> int:
    OUT.mkdir(exist_ok=True)
    ids = seed()
    print(f"seeded 14-day course: patient={ids['patient_id'][:8]} "
          f"medicine={ids['medicine_id'][:8]}\n")

    try:
        # ---------------------------------------------------- the numbers
        print("=== the data layer agrees with what was seeded")
        course = data.for_course(ids["patient_id"], ids["medicine_id"])
        check("on time", course.on_time == EXPECT_ON_TIME,
              f"{course.on_time} != {EXPECT_ON_TIME}")
        check("late", course.late == EXPECT_LATE, f"{course.late} != {EXPECT_LATE}")
        check("missed", course.missed == EXPECT_MISSED,
              f"{course.missed} != {EXPECT_MISSED}")
        check("declined", course.skipped == EXPECT_SKIPPED,
              f"{course.skipped} != {EXPECT_SKIPPED}")
        check("taken total", course.taken == EXPECT_TAKEN)
        check("nothing left pending", course.pending == 0, str(course.pending))
        check("adherence is taken/decided",
              course.percent == round(EXPECT_TAKEN / EXPECT_DECIDED * 100),
              f"{course.percent}")
        check("tenure is the schedule's, inclusive",
              course.start_date == START and course.end_date == END)
        check("both symptoms found", len(course.symptoms) == 2,
              str(len(course.symptoms)))
        check("missed log has every unconfirmed dose",
              len(course.missed_log) == EXPECT_MISSED + EXPECT_SKIPPED,
              str(len(course.missed_log)))
        check("the emergency symptom kept its severity",
              any(s.severity == "emergency" for s in course.symptoms))
        check("hardest time is the evening dose",
              course.hardest_time is not None and course.hardest_time.hhmm == "20:00",
              str(course.hardest_time and course.hardest_time.hhmm))

        print("\n=== verbatim, untranslated, uninterpreted")
        urdu = [m.said for m in course.missed_log if m.said]
        check("Urdu reason stored and returned unchanged",
              "گولی ختم ہو گئی ہے" in urdu, str(urdu)[:120])
        check("Roman Urdu reason too",
              any("so gayi thi" in u for u in urdu))
        check("a dose with no reason is still listed",
              any(not m.said for m in course.missed_log))

        # ---------------------------------------------------- the PDFs
        print("\n=== both PDFs render")
        doc = doctor_pdf.build(ids["patient_id"], ids["medicine_id"])
        care_en = caretaker_pdf.build(ids["patient_id"], ids["medicine_id"], lang="en")
        care_ur = caretaker_pdf.build(ids["patient_id"], ids["medicine_id"], lang="ur")
        (OUT / "doctor.pdf").write_bytes(doc)
        (OUT / "caretaker-en.pdf").write_bytes(care_en)
        (OUT / "caretaker-ur.pdf").write_bytes(care_ur)

        for name, blob in (("doctor", doc), ("caretaker en", care_en),
                           ("caretaker ur", care_ur)):
            check(f"{name} is a real PDF", blob[:5] == b"%PDF-", str(blob[:8]))
            check(f"{name} is not empty", len(blob) > 8000, f"{len(blob)} bytes")
        check("one page each",
              all(b.count(b"/Type /Page\n") <= 1 or b"/Count 1" in b
                  for b in (doc, care_en, care_ur)))
        check("the two caretaker languages differ", care_en != care_ur)

        print("\n=== the doctor report says what invariant 11 requires")
        if page_text is None:
            warn("read the rendered pages back", False,
                 "pypdfium2 is not installed, so nothing was read back out of "
                 "the PDFs. pip install pypdfium2 to check their contents.")
        else:
            text = page_text(doc)
            check("carries the not-observed-ingestion line",
                  "not observed ingestion" in text, "disclaimer missing")
            check("says confirmations are patient-reported",
                  "patient-reported confirmations" in text)
            check("says pending doses are not counted as missed",
                  "excluded from the adherence figure" in text)
            check("names the patient and the medicine",
                  "Zubaida" in text and "Panadol" in text)
            check("shows the adherence percentage",
                  f"{course.percent}%" in text, f"{course.percent}% missing")
            check("the patient's Urdu words reach the page",
                  "گولی" in text, "verbatim Urdu not rendered")
            check("Urdu is shaped, not reversed",
                  "ہے" in text and "ی" in text)
            check("the doctor report is one page", page_count(doc) == 1,
                  str(page_count(doc)))

            print("\n=== the caretaker report is a letter, not a spreadsheet")
            care_text = page_text(care_en)
            check("no adherence percentage anywhere",
                  "%" not in care_text, "a percentage leaked in")
            check("no clinical vocabulary",
                  "adherence" not in care_text.lower()
                  and "distribution" not in care_text.lower())
            check("says it in doses a person can hold",
                  f"took {course.taken} of the {course.decided} doses" in care_text,
                  care_text[:120])
            check("points at the doctor rather than advising",
                  "not a substitute for" in care_text)
            check("quotes the patient verbatim here too", "گولی" in care_text)
            check("the caretaker report is one page", page_count(care_en) == 1,
                  str(page_count(care_en)))
            check("the Urdu edition is Roman Urdu, not English",
                  "khurakein" in page_text(care_ur))

        # ---------------------------------------------------- persistence
        print("\n=== generate() records a row and a share link")
        row, blob = await asyncio.to_thread(
            service.generate, "doctor", ids["patient_id"], ids["medicine_id"],
            trigger="on_demand", lang="en")
        check("row written", bool(row.id))
        check("trigger recorded", row.trigger == "on_demand", row.trigger)
        check("period matches the course",
              row.period_start == START and row.period_end == END)
        check("storage key is namespaced by patient",
              row.storage_key.startswith(ids["patient_id"]), row.storage_key)

        token = storage.share_token(row.id)
        check("share token is stable", token == storage.share_token(row.id))
        check("share token accepts itself", storage.token_ok(row.id, token))
        check("share token rejects a wrong one",
              not storage.token_ok(row.id, "0" * 32))
        check("share token rejects another report's token",
              not storage.token_ok(row.id, storage.share_token("someone-else")))

        print("\n=== fetch() returns the report even with no archive")
        found = await asyncio.to_thread(service.fetch, row.id)
        check("fetch found it", found is not None)
        if found:
            _, refetched = found
            check("regenerated copy is a PDF", refetched[:5] == b"%PDF-")
        warn("archiving to Supabase Storage is configured",
             storage.is_configured(),
             "SUPABASE_SERVICE_KEY not set. Reports still generate and still "
             "open from the WhatsApp link - they are just not archived.")
        if storage.is_configured():
            check("the archived copy comes back",
                  storage.download(row.storage_key) is not None)

        # ---------------------------------------------------- the daily job
        print("\n=== the course-end job")
        with session_scope() as s:
            s.exec(delete(Report).where(Report.patient_id == ids["patient_id"]))
            s.commit()

        finished = await asyncio.to_thread(service.finished_courses)
        mine = [c for c in finished if c["medicine_id"] == ids["medicine_id"]]
        check("a course that ended yesterday is picked up", len(mine) == 1,
              f"{len(mine)} matches")
        if mine:
            check("both kinds are missing to start with",
                  sorted(mine[0]["missing"]) == ["caretaker", "doctor"],
                  str(mine[0]["missing"]))

        SENT.clear()
        counts = await ticker.course_end_reports()
        print(f"     job returned {counts}")
        kinds = await asyncio.to_thread(
            service.existing_kinds, ids["patient_id"], ids["medicine_id"],
            "course_end")
        check("both reports generated automatically",
              kinds == {"doctor", "caretaker"}, str(kinds))
        mine_sent = [m for m in SENT if m["to"] == ids["carer_phone"]]
        check("the caretaker was messaged", len(mine_sent) >= 1,
              f"{len(SENT)} messages, none to {ids['carer_phone']}")
        if mine_sent:
            body = mine_sent[-1]["body"]
            print(f"     message: {body[:150]}")
            check("message carries both links",
                  body.count("/api/reports/") == 2, body[:200])
            check("links carry a token", "?t=" in body, body[:200])

        print("\n=== it does not send the same reports again tomorrow")
        SENT.clear()
        counts2 = await ticker.course_end_reports()
        again = [c for c in await asyncio.to_thread(service.finished_courses)
                 if c["medicine_id"] == ids["medicine_id"]]
        check("the finished course is no longer outstanding", not again,
              str(again))
        check("no second pair of reports", counts2["reports"] == 0,
              str(counts2))
        check("no second message to this caretaker",
              not [m for m in SENT if m["to"] == ids["carer_phone"]],
              str(len(SENT)))

        # ---------------------------------------------------- a live course
        print("\n=== a course still running is left alone")
        with session_scope() as s:
            sched = s.get(Schedule, ids["schedule_id"])
            sched.end_date = date.today() + timedelta(days=3)
            s.add(sched)
            s.commit()
            s.exec(delete(Report).where(Report.patient_id == ids["patient_id"]))
            s.commit()
        running = [c for c in await asyncio.to_thread(service.finished_courses)
                   if c["medicine_id"] == ids["medicine_id"]]
        check("an unfinished course is not reported on", not running, str(running))

    finally:
        cleanup(ids)
        print(f"\ncleaned up. PDFs left in {OUT} for eyeballing.")

    print(f"\n{'=' * 58}\n  {len(OK)} passed, {len(BAD)} failed"
          + (f", {len(WARN)} warning(s)" if WARN else ""))
    for f in BAD:
        print(f"    FAILED: {f}")
    for w in WARN:
        print(f"    WARNING: {w}")
    return 1 if BAD else 0


sys.exit(asyncio.run(main()))
