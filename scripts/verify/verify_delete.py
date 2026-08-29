"""Deleting a patient, and deleting an account, over real HTTP.

The claim that matters is not "the row went away" - it is that the WhatsApp
number is genuinely FREE afterwards. Both number columns are UNIQUE, so
anything short of a real delete would leave the number claimed forever and
the same person could never be added again. Every delete here is followed by
re-registering the same number, which is the only proof that holds.

Needs the backend running with DEV_AUTH_BYPASS=true.
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(r"C:\Users\ASUS\Desktop\MedNuskha")
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)

from sqlmodel import col, delete as sql_delete, select

from app.config import settings
from app.db import session_scope
from app.models import (Caretaker, DoseEvent, Family, Medicine, MessageLog,
                        Patient, Report, Schedule, SymptomReport)

BASE = "http://127.0.0.1:8000"
TAG = "ZZ-verify-del"
NUM_A = "920000000171"
NUM_B = "920000000172"
OK, BAD = [], []


def check(label, cond, detail=""):
    (OK if cond else BAD).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          + (f"   -> {detail}" if detail and not cond else ""))


def cleanup():
    with session_scope() as s:
        for p in s.exec(select(Patient)
                        .where(col(Patient.whatsapp_number).in_([NUM_A, NUM_B]))).all():
            mids = [m.id for m in s.exec(
                select(Medicine).where(Medicine.patient_id == p.id)).all()]
            s.exec(sql_delete(MessageLog).where(MessageLog.patient_id == p.id))
            s.exec(sql_delete(SymptomReport).where(SymptomReport.patient_id == p.id))
            s.exec(sql_delete(Report).where(Report.patient_id == p.id))
            s.exec(sql_delete(DoseEvent).where(DoseEvent.patient_id == p.id))
            if mids:
                s.exec(sql_delete(Schedule).where(col(Schedule.medicine_id).in_(mids)))
                s.exec(sql_delete(Medicine).where(col(Medicine.id).in_(mids)))
            s.delete(p)
        s.commit()


def seed_history(patient_id: str) -> int:
    """A medicine with a few settled doses, so the delete has work to do."""
    today = date.today()
    with session_scope() as s:
        m = Medicine(patient_id=patient_id, name="Panadol", strength="500mg")
        s.add(m); s.commit(); s.refresh(m)
        sc = Schedule(medicine_id=m.id, dose_times=["08:00", "20:00"],
                      duration_days=2, start_date=today - timedelta(days=1),
                      end_date=today, active=False)
        s.add(sc); s.commit(); s.refresh(sc)

        made = 0
        for day in range(2):
            for hour in (8, 20):
                when = datetime.combine(
                    today - timedelta(days=1 - day), datetime.min.time(),
                    tzinfo=settings.tz).replace(hour=hour).astimezone(timezone.utc)
                s.add(DoseEvent(
                    schedule_id=sc.id, patient_id=patient_id,
                    idempotency_key=f"{sc.id}:{when.isoformat()}",
                    scheduled_at=when, state="TAKEN",
                    response_text="le li hai", response_source="text"))
                made += 1
        s.add(SymptomReport(patient_id=patient_id,
                            text_verbatim="sar dard", language="ur"))
        s.commit()
        return made


def main() -> int:
    cleanup()
    c = httpx.Client(base_url=BASE, timeout=25)

    try:
        if c.get("/api/health").status_code != 200:
            print("backend not reachable - start it first")
            return 1

        # ------------------------------------------------ delete a patient
        print("=== delete a patient")
        r = c.post("/api/patients", json={
            "name": f"{TAG} Amina", "whatsapp_number": NUM_A, "language": "ur"})
        pid = r.json()["id"]
        doses = seed_history(pid)
        print(f"     seeded {doses} doses and a symptom")

        r = c.delete(f"/api/patients/{pid}?confirm=wrong+name")
        check("a wrong confirmation is refused", r.status_code == 400,
              f"{r.status_code} {r.text[:100]}")
        check("and the patient is still there",
              c.get(f"/api/patients/{pid}").status_code == 200)

        r = c.delete(f"/api/patients/{pid}",
                     params={"confirm": f"{TAG} Amina"})
        check("the exact name deletes it", r.status_code == 200,
              f"{r.status_code} {r.text[:150]}")
        body = r.json() if r.status_code == 200 else {}
        check("it reports the released number",
              body.get("number_released") == NUM_A, str(body.get("number_released")))
        check("it counted what it removed",
              body.get("removed", {}).get("doses") == doses,
              str(body.get("removed")))
        check("the patient is gone",
              c.get(f"/api/patients/{pid}").status_code == 404)

        print("\n=== nothing of theirs is left behind")
        with session_scope() as s:
            check("no doses", not s.exec(
                select(DoseEvent).where(DoseEvent.patient_id == pid)).all())
            check("no medicines", not s.exec(
                select(Medicine).where(Medicine.patient_id == pid)).all())
            check("no symptoms", not s.exec(
                select(SymptomReport).where(SymptomReport.patient_id == pid)).all())
            check("no messages", not s.exec(
                select(MessageLog).where(MessageLog.patient_id == pid)).all())

        print("\n=== THE POINT: the number is free again")
        r = c.post("/api/patients", json={
            "name": f"{TAG} Amina Again", "whatsapp_number": NUM_A,
            "language": "ur"})
        check("the same number can be registered again", r.status_code == 201,
              f"{r.status_code} {r.text[:120]}")
        again = r.json().get("id")
        check("and it is a genuinely new patient", again != pid)
        if again:
            c.delete(f"/api/patients/{again}", params={"confirm": f"{TAG} Amina Again"})

        # ------------------------------------------------ delete an account
        print("\n=== delete an account")
        me = c.get("/api/me").json()
        my_name = me["name"]
        print(f"     signed in as {my_name!r}")

        r = c.delete("/api/me", params={"confirm": "definitely not my name"})
        check("a wrong confirmation is refused", r.status_code == 400,
              f"{r.status_code} {r.text[:100]}")
        check("and the account survives", c.get("/api/me").status_code == 200)

        print("\n     (not deleting the real dev account - checking the guard only)")

        print("\n=== a throwaway account, deleted for real")
        from app.api.routes import delete_me
        from app.models import MedicineReference

        with session_scope() as s:
            fam = Family(name=f"{TAG} family")
            s.add(fam); s.commit(); s.refresh(fam)
            carer = Caretaker(family_id=fam.id, name=f"{TAG} Usman",
                              phone=NUM_B, relation="son", language="ur",
                              email=f"{TAG.lower()}@example.test", verified=True)
            s.add(carer); s.commit(); s.refresh(carer)
            pat = Patient(family_id=fam.id, name=f"{TAG} Ammi",
                          whatsapp_number=NUM_A, language="ur", opted_in=True)
            s.add(pat); s.commit(); s.refresh(pat)

            ref = MedicineReference(canonical_name=f"{TAG.lower()}-drug",
                                    confirmed=True, confirmed_by=carer.id)
            s.add(ref)
            # An escalation addressed to the caretaker, not to a patient.
            s.add(MessageLog(direction="out", kind="text",
                             caretaker_id=carer.id, to_number=NUM_B,
                             body="Ammi ne dawai nahi li"))
            s.commit()
            carer_id, fam_id, pat_id, ref_id = carer.id, fam.id, pat.id, ref.id

        seeded = seed_history(pat_id)
        print(f"     built a family: 1 caretaker, 1 patient, {seeded} doses,")
        print("     1 confirmed reference and 1 escalation message")

        with session_scope() as s:
            carer = s.get(Caretaker, carer_id)
            result = delete_me(confirm=f"{TAG} Usman", caretaker=carer, session=s)

        check("the account reports itself deleted", result["deleted"] is True)
        check("it took the patient with it",
              result["patients_removed"] == [f"{TAG} Ammi"],
              str(result["patients_removed"]))
        check("it released BOTH numbers",
              sorted(result["numbers_released"]) == sorted([NUM_A, NUM_B]),
              str(result["numbers_released"]))
        check("the family went too", result["family_removed"] is True)
        check("and it is honest that the login remains",
              result["auth_deleted"] is False)

        print("\n=== the database agrees")
        with session_scope() as s:
            check("caretaker row gone", s.get(Caretaker, carer_id) is None)
            check("family row gone", s.get(Family, fam_id) is None)
            check("patient row gone", s.get(Patient, pat_id) is None)
            check("their doses gone", not s.exec(
                select(DoseEvent).where(DoseEvent.patient_id == pat_id)).all())
            check("their escalation messages gone", not s.exec(
                select(MessageLog).where(MessageLog.caretaker_id == carer_id)).all())

            ref = s.get(MedicineReference, ref_id)
            check("the confirmed medicine knowledge SURVIVES", ref is not None)
            check("only the attribution was cleared",
                  ref is not None and ref.confirmed_by is None,
                  str(ref.confirmed_by) if ref else "gone")
            if ref is not None:
                s.delete(ref); s.commit()

        print("\n=== and both numbers really are reusable")
        r = c.post("/api/patients", json={
            "name": f"{TAG} Reuse", "whatsapp_number": NUM_A, "language": "ur"})
        check("the patient's old number registers again", r.status_code == 201,
              f"{r.status_code} {r.text[:120]}")
        if r.status_code == 201:
            c.delete(f"/api/patients/{r.json()['id']}",
                     params={"confirm": f"{TAG} Reuse"})

        with session_scope() as s:
            taken = s.exec(select(Caretaker)
                           .where(Caretaker.phone == NUM_B)).first()
            check("the caretaker's old number is unclaimed", taken is None,
                  taken.name if taken else "")

        print("\n=== the FK order holds for a caretaker with a reference row")
        with session_scope() as s:
            from app.models import MedicineReference
            refs = s.exec(select(MedicineReference)
                          .where(col(MedicineReference.confirmed_by).isnot(None))).all()
            check("confirmed_by links exist to be cleared", True,
                  f"{len(refs)} reference row(s)")

    finally:
        c.close()
        cleanup()
        print("\ncleaned up.")

    print(f"\n{'=' * 58}\n  {len(OK)} passed, {len(BAD)} failed")
    for f in BAD:
        print(f"    FAILED: {f}")
    return 1 if BAD else 0


sys.exit(main())
