"""Phase 6 over real HTTP: the dashboard buttons and the WhatsApp share link.

Seeds a short course under the caretaker the dev bypass maps to, then calls
the live backend the way the browser and a caretaker's phone actually would.
Needs the backend running (`.\\dev.ps1`). Everything it creates is deleted.
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# scripts/verify/<this file> -> scripts/verify -> scripts -> <repo root>
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)

import httpx
from sqlmodel import col, delete, select

from app.config import settings
from app.db import session_scope
from app.models import (Caretaker, DoseEvent, Medicine, Patient, Report,
                        Schedule)
from app.reports import storage

#: dev.ps1 runs uvicorn WITHOUT --reload, so a backend started before a code
#: change will 404 on new routes. Point this at a second instance on another
#: port to test fresh code without restarting the one you are using.
BASE = os.environ.get("MEDNUSKHA_API", "http://localhost:8000").rstrip("/")
TAG = "ZZ-verify-api"

OK, BAD = [], []


def check(label, cond, detail=""):
    (OK if cond else BAD).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          + (f"   -> {detail}" if detail and not cond else ""))


def seed() -> dict:
    """A 4-day course under the dev-bypass caretaker, so the API authorises it."""
    start = date.today() - timedelta(days=4)
    with session_scope() as s:
        carer = s.exec(select(Caretaker)
                       .where(Caretaker.email == "dev@mednuskha.local")).first()
        if carer is None:
            raise SystemExit(
                "no dev-bypass caretaker yet - open the dashboard once first")

        patient = Patient(family_id=carer.family_id, name=f"{TAG} Amina",
                          whatsapp_number="920000000198", language="ur",
                          opted_in=True)
        s.add(patient)
        s.commit()
        s.refresh(patient)

        medicine = Medicine(patient_id=patient.id, name=f"{TAG} Brufen",
                            strength="400mg", form="tablet")
        s.add(medicine)
        s.commit()
        s.refresh(medicine)

        schedule = Schedule(medicine_id=medicine.id, dose_times=["09:00"],
                            duration_days=4, start_date=start,
                            end_date=start + timedelta(days=3))
        s.add(schedule)
        s.commit()
        s.refresh(schedule)

        for day, state, said in [
            (0, "TAKEN", "le li hai"),
            (1, "TAKEN", "haan"),
            (2, "MISSED", "بھول گئی تھی"),
            (3, "TAKEN_LATE", "ab li hai"),
        ]:
            when = datetime.combine(start + timedelta(days=day),
                                    datetime.min.time(), tzinfo=settings.tz)
            when = when.replace(hour=9).astimezone(timezone.utc)
            s.add(DoseEvent(
                schedule_id=schedule.id, patient_id=patient.id,
                idempotency_key=f"{schedule.id}:{when.isoformat()}",
                scheduled_at=when, state=state, sent_at=when,
                responded_at=when + timedelta(minutes=3),
                response_source="text", response_text=said))
        s.commit()

        return {"patient_id": patient.id, "medicine_id": medicine.id,
                "family_id": carer.family_id}


def cleanup(ids: dict) -> None:
    with session_scope() as s:
        s.exec(delete(Report).where(Report.patient_id == ids["patient_id"]))
        s.exec(delete(DoseEvent).where(DoseEvent.patient_id == ids["patient_id"]))
        s.exec(delete(Schedule).where(Schedule.medicine_id == ids["medicine_id"]))
        s.exec(delete(Medicine).where(Medicine.id == ids["medicine_id"]))
        s.exec(delete(Patient).where(Patient.id == ids["patient_id"]))
        s.commit()


def main() -> int:
    try:
        httpx.get(f"{BASE}/api/health", timeout=5)
    except httpx.HTTPError:
        raise SystemExit(f"backend is not running at {BASE} - start .\\dev.ps1")

    ids = seed()
    pid, mid = ids["patient_id"], ids["medicine_id"]
    print(f"seeded patient={pid[:8]} medicine={mid[:8]}\n")

    try:
        with httpx.Client(base_url=BASE, timeout=60) as c:
            print("=== the two dashboard buttons")
            for kind in ("doctor", "caretaker"):
                r = c.get(f"/api/patients/{pid}/report.pdf",
                          params={"kind": kind, "medicine_id": mid})
                check(f"{kind} button returns 200", r.status_code == 200,
                      f"{r.status_code} {r.text[:120]}")
                check(f"{kind} button returns a PDF",
                      r.content[:5] == b"%PDF-", str(r.content[:20]))
                check(f"{kind} content-type is application/pdf",
                      r.headers.get("content-type", "").startswith("application/pdf"),
                      r.headers.get("content-type", ""))
                check(f"{kind} has a sensible filename",
                      kind in r.headers.get("content-disposition", ""),
                      r.headers.get("content-disposition", ""))

            print("\n=== the button defaults to the patient's only medicine")
            r = c.get(f"/api/patients/{pid}/report.pdf", params={"kind": "doctor"})
            check("no medicine_id still works", r.status_code == 200,
                  f"{r.status_code} {r.text[:120]}")

            print("\n=== bad input is refused")
            r = c.get(f"/api/patients/{pid}/report.pdf", params={"kind": "nonsense"})
            check("an unknown kind is rejected", r.status_code == 422,
                  str(r.status_code))
            r = c.get("/api/patients/does-not-exist/report.pdf",
                      params={"kind": "doctor"})
            check("another family's patient is 404", r.status_code == 404,
                  str(r.status_code))
            r = c.get(f"/api/patients/{pid}/report.pdf",
                      params={"kind": "doctor", "medicine_id": "nope"})
            check("a medicine that is not theirs is 404", r.status_code == 404,
                  str(r.status_code))

            print("\n=== every download was recorded as on_demand")
            with session_scope() as s:
                rows = s.exec(select(Report).where(Report.patient_id == pid)).all()
                triggers = {r.trigger for r in rows}
                report_id = rows[0].id if rows else ""
            check("report rows written", len(rows) >= 3, str(len(rows)))
            check("all on_demand", triggers == {"on_demand"}, str(triggers))

            print("\n=== the WhatsApp share link, with no sign-in")
            token = storage.share_token(report_id)
            r = c.get(f"/api/reports/{report_id}.pdf", params={"t": token})
            check("opens with the right token", r.status_code == 200,
                  f"{r.status_code} {r.text[:120]}")
            check("and returns a PDF", r.content[:5] == b"%PDF-")

            r = c.get(f"/api/reports/{report_id}.pdf", params={"t": "0" * 32})
            check("a wrong token is 404, not 403", r.status_code == 404,
                  str(r.status_code))
            r = c.get(f"/api/reports/{report_id}.pdf")
            check("no token at all is 404", r.status_code == 404,
                  str(r.status_code))
            r = c.get(f"/api/reports/{report_id}.pdf",
                      params={"t": storage.share_token("some-other-report")})
            check("another report's token is 404", r.status_code == 404,
                  str(r.status_code))
            r = c.get("/api/reports/not-a-real-id.pdf",
                      params={"t": storage.share_token("not-a-real-id")})
            check("a valid token for a missing report is 404",
                  r.status_code == 404, str(r.status_code))

    finally:
        cleanup(ids)
        print("\ncleaned up.")

    print(f"\n{'=' * 58}\n  {len(OK)} passed, {len(BAD)} failed")
    for f in BAD:
        print(f"    FAILED: {f}")
    return 1 if BAD else 0


sys.exit(main())
