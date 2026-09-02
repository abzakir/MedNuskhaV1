"""Delete a patient and everything hanging off them, in strict FK order.

Order matters and has bitten repeatedly:
    message_log / symptom_report  ->  dose_event  ->  schedule  ->  medicine
    ->  report  ->  patient
Each level is committed before the next, or Postgres refuses the parent.
"""
import sys
from pathlib import Path

# scripts/verify/<this file> -> scripts/verify -> scripts -> <repo root>
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlmodel import select

from app.db import session_scope
from app.models import (DoseEvent, Medicine, MessageLog, Patient, Report,
                        Schedule, SymptomReport)


def purge(number: str) -> bool:
    with session_scope() as s:
        patient = s.exec(
            select(Patient).where(Patient.whatsapp_number == number)).first()
        if patient is None:
            return False
        pid = patient.id

        schedule_ids = [
            sc.id
            for m in s.exec(select(Medicine).where(Medicine.patient_id == pid)).all()
            for sc in s.exec(select(Schedule).where(Schedule.medicine_id == m.id)).all()
        ]

        dose_ids = {d.id for d in s.exec(
            select(DoseEvent).where(DoseEvent.patient_id == pid)).all()}
        for sid in schedule_ids:
            dose_ids |= {d.id for d in s.exec(
                select(DoseEvent).where(DoseEvent.schedule_id == sid)).all()}

        # 1. anything pointing at a dose
        for did in dose_ids:
            for row in s.exec(select(MessageLog).where(
                    MessageLog.dose_event_id == did)).all():
                s.delete(row)
            for row in s.exec(select(SymptomReport).where(
                    SymptomReport.dose_event_id == did)).all():
                s.delete(row)
        s.commit()

        # 2. anything pointing at the patient
        for model in (MessageLog, SymptomReport, Report):
            for row in s.exec(select(model).where(model.patient_id == pid)).all():
                s.delete(row)
        s.commit()

        # 3. doses, then schedules, then medicines
        for did in dose_ids:
            row = s.get(DoseEvent, did)
            if row:
                s.delete(row)
        s.commit()

        for sid in schedule_ids:
            row = s.get(Schedule, sid)
            if row:
                s.delete(row)
        s.commit()

        for m in s.exec(select(Medicine).where(Medicine.patient_id == pid)).all():
            s.delete(m)
        s.commit()

        s.delete(s.get(Patient, pid))
        s.commit()
        return True


for number in sys.argv[1:]:
    print(f"  {number}: {'removed' if purge(number) else 'not found'}")
