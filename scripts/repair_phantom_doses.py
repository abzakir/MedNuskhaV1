"""Remove doses that were due before their medicine existed.

Until 2026-08-30, `materialise_doses` created a row for every dose time on the
day a medicine was added - including times that had already gone by. The next
tick found them past the escalation window and wrote them straight to MISSED,
so a medicine added at 2pm reported a missed 9am dose, against a patient who
had never been asked anything. `ticker._remindable_from()` now refuses to
create them; this clears the ones already recorded.

Only rows that are unambiguously phantom are touched:

  * the dose time is BEFORE the schedule's own `created_at`, and
  * nothing was ever sent for it (`sent_at` is null), and
  * no caretaker was ever alerted about it.

A dose that reached the patient, or that a caretaker was told about, is
history and is left alone even if it looks odd - the reports are made of it.

    python scripts/repair_phantom_doses.py              # show what it would do
    python scripts/repair_phantom_doses.py --apply      # do it
"""

from __future__ import annotations

import argparse
import sys
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlmodel import col, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import (DoseEvent, Medicine, MessageLog, Patient,  # noqa: E402
                        Schedule, SymptomReport)


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _local(dt) -> str:
    return _aware(dt).astimezone(settings.tz).strftime("%Y-%m-%d %H:%M")


def find() -> list[dict]:
    """Every dose that was due before the medicine it belongs to was added."""
    out: list[dict] = []
    with session_scope() as session:
        rows = session.exec(
            select(DoseEvent, Schedule, Medicine, Patient)
            .join(Schedule, Schedule.id == DoseEvent.schedule_id)
            .join(Medicine, Medicine.id == Schedule.medicine_id)
            .join(Patient, Patient.id == DoseEvent.patient_id)
            .where(col(DoseEvent.sent_at).is_(None))
            .where(col(DoseEvent.caretaker_alerted_at).is_(None))
        ).all()
        for dose, schedule, medicine, patient in rows:
            if _aware(dose.scheduled_at) >= _aware(schedule.created_at):
                continue
            out.append({
                "id": dose.id,
                "patient": patient.name,
                "medicine": medicine.name,
                "due": _local(dose.scheduled_at),
                "added": _local(schedule.created_at),
                "state": dose.state,
            })
    return sorted(out, key=lambda r: (r["patient"], r["due"]))


def remove(dose_ids: list[str]) -> int:
    """Delete the rows, unlinking anything that points at them first.

    Messages are unlinked rather than deleted: if one was somehow logged
    against a phantom dose, the message still happened.
    """
    if not dose_ids:
        return 0
    with session_scope() as session:
        for row in session.exec(select(MessageLog).where(
                col(MessageLog.dose_event_id).in_(dose_ids))).all():
            row.dose_event_id = None
            session.add(row)
        for row in session.exec(select(SymptomReport).where(
                col(SymptomReport.dose_event_id).in_(dose_ids))).all():
            row.dose_event_id = None
            session.add(row)
        session.commit()

        gone = 0
        for dose_id in dose_ids:
            row = session.get(DoseEvent, dose_id)
            if row is not None:
                session.delete(row)
                gone += 1
        session.commit()
    return gone


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="actually delete them (default is a dry run)")
    args = parser.parse_args()

    if not settings.database_configured:
        print("DATABASE_URL is not set.")
        return 1

    found = find()
    if not found:
        print("Nothing to repair - no dose predates the medicine it belongs to.")
        return 0

    print(f"{len(found)} dose(s) were due before their medicine was added:\n")
    print(f"  {'patient':<22} {'medicine':<16} {'due':<17} {'added':<17} state")
    for r in found:
        print(f"  {r['patient']:<22} {r['medicine']:<16} {r['due']:<17} "
              f"{r['added']:<17} {r['state']}")

    if not args.apply:
        print("\nDry run. Re-run with --apply to remove them.")
        return 0

    gone = remove([r["id"] for r in found])
    print(f"\nRemoved {gone} dose(s). They were never sent to anybody, so no "
          f"message, reply or report loses anything.")
    return 0


sys.exit(main())
