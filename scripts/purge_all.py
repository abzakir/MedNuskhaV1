"""Empty every table, to start testing from nothing.

Deletes ALL patients, caretakers, families, medicines, schedules, doses,
messages, symptoms, prescriptions and reports. There is no undo and nothing is
exported first.

The `medicine_reference` knowledge cache goes too, so the next medicine you add
runs a fresh AI lookup and shows you the confirm screen again instead of
answering from a row somebody already confirmed. `--keep-medicine-knowledge`
leaves it in place.

**Supabase Auth logins are not touched.** The backend deliberately holds no
service key, so it cannot delete an account. Signing in again with the same
email gives you a brand new, empty caretaker and family - which is exactly what
you want for a clean test.

    python scripts/purge_all.py                # show what would go
    python scripts/purge_all.py --apply        # do it
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import delete, func, select as sa_select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import (Caretaker, DoseEvent, Family, Medicine,  # noqa: E402
                        MedicineReference, MessageLog, Patient, Prescription,
                        Report, Schedule, SymptomReport)

#: Child before parent, or Postgres refuses. `medicine` points at
#: `medicine_reference`, and `medicine_reference.confirmed_by` points back at
#: `caretaker`, so the knowledge rows sit between the two.
ORDER = [
    MessageLog,          # -> patient, caretaker, dose_event
    SymptomReport,       # -> patient, dose_event
    Report,              # -> patient, medicine
    Prescription,        # -> patient, caretaker
    DoseEvent,           # -> schedule, patient
    Schedule,            # -> medicine
    Medicine,            # -> patient, medicine_reference
    Patient,             # -> family
    MedicineReference,   # -> caretaker
    Caretaker,           # -> family
    Family,
]


def counts() -> dict[str, int]:
    with session_scope() as session:
        return {m.__tablename__: session.exec(
            sa_select(func.count()).select_from(m)).scalar_one()
            for m in ORDER}


def purge(keep_knowledge: bool) -> dict[str, int]:
    removed: dict[str, int] = {}
    with session_scope() as session:
        for model in ORDER:
            if keep_knowledge and model is MedicineReference:
                # It stays, but it may not keep pointing at caretakers that
                # are about to stop existing.
                session.execute(
                    MedicineReference.__table__.update()
                    .values(confirmed_by=None))
                continue
            result = session.execute(delete(model.__table__))
            removed[model.__tablename__] = result.rowcount or 0
        session.commit()
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="actually delete (default is a dry run)")
    parser.add_argument("--keep-medicine-knowledge", action="store_true",
                        help="leave medicine_reference alone, so a medicine "
                             "you add is recognised without an AI lookup")
    args = parser.parse_args()

    if not settings.database_configured:
        print("DATABASE_URL is not set.")
        return 1

    before = counts()
    total = sum(before.values())
    print(f"{ROOT.name} - {settings.supabase_url or settings.database_url[:40]}\n")
    for table, n in before.items():
        keep = args.keep_medicine_knowledge and table == "medicine_reference"
        print(f"  {table:<20} {n:>6}{'   (kept)' if keep else ''}")
    print(f"  {'':<20} {'-'*6}\n  {'total':<20} {total:>6} row(s)")

    if not args.apply:
        print("\nDry run. Re-run with --apply to delete all of it.")
        return 0
    if total == 0:
        print("\nAlready empty - nothing to do.")
        return 0

    removed = purge(args.keep_medicine_knowledge)
    print(f"\nDeleted {sum(removed.values())} row(s). The database is empty and "
          f"ready for a fresh test.")
    print("Your Supabase login still exists - signing in creates a new, empty "
          "caretaker and family.")
    return 0


sys.exit(main())
