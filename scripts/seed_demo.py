"""Seed a demo-worthy database in one command. Phase 8.

Creates one caretaker, one patient, three real medicines and 14 days of
backdated dose events with a believable mix of taken, taken-late and missed -
so the dashboard, both PDFs and the WhatsApp history all have something worth
showing before anyone has waited a fortnight.

    make seed                    (or .\\seed.ps1 on Windows)
    make seed ARGS="--help"      every option

It is safe to run twice: everything it creates is tagged, and a second run
deletes the previous demo before rebuilding it. It never touches rows it did
not create.

By default the patient's number is a placeholder that cannot receive anything.
Pass --phone with a real WhatsApp number when you want the demo to be live -
and note that a real number will start receiving reminders at the next tick.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from sqlmodel import col, delete, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import (Caretaker, DoseEvent, Family, Medicine,  # noqa: E402
                        MedicineReference, MessageLog, Patient, Report,
                        Schedule, SymptomReport)

#: Everything this script creates carries this, so a re-run can find it again
#: and nothing else is ever deleted.
TAG = "[demo]"
#: Reserved test range. Nothing real is on it, so a stray reminder goes nowhere.
DEMO_PATIENT_NUMBER = "920000000001"
DEMO_CARETAKER_NUMBER = "920000000002"

DAYS = 14

# --------------------------------------------------------------------------
# the three medicines
# --------------------------------------------------------------------------

#: Real medicines a Pakistani household would actually have, with the purpose
#: and food rule a caretaker would have confirmed on the dashboard. These are
#: written as CONFIRMED reference rows - invariant 9 means the agent will not
#: say a word about a medicine that is not.
MEDICINES = [
    {
        "name": "Panadol",
        "strength": "500mg",
        "form": "tablet",
        "purpose_ur": "bukhar aur dard ke liye",
        "purpose_en": "for fever and pain",
        "food_rule": "Khane ke baad lein.",
        "common_timing": "subah aur raat",
        "dose_times": ["08:00", "20:00"],
        #: How this course actually went. One index per dose, in order.
        "story": "steady",
    },
    {
        "name": "Amlodipine",
        "strength": "5mg",
        "form": "tablet",
        "purpose_ur": "blood pressure ke liye",
        "purpose_en": "for blood pressure",
        "food_rule": "Subah khane se pehle lein.",
        "common_timing": "subah",
        "dose_times": ["08:00"],
        "story": "perfect",
    },
    {
        "name": "Metformin",
        "strength": "500mg",
        "form": "tablet",
        "purpose_ur": "sugar ke liye",
        "purpose_en": "for blood sugar",
        "food_rule": "Khane ke sath lein.",
        "common_timing": "subah aur raat",
        "dose_times": ["09:00", "21:00"],
        "story": "evenings_are_hard",
    },
]

#: What the patient said. Real replies, in the mix of scripts they arrive in -
#: the doctor report quotes these verbatim, so they need to look real.
TAKEN_REPLIES = ["haan le li", "le li hai", "ji han", "لے لی ہے", "ji", "haan"]
LATE_REPLIES = ["abhi li hai", "der ho gayi, ab li hai", "ابھی لی ہے"]
MISSED_REASONS = [
    "so gayi thi, yaad hi nahi raha",
    "گولی ختم ہو گئی ہے",
    "ابھی نہیں، بعد میں لوں گی",
    "bahar thi, ghar aa kar loongi",
    "",                                     # sometimes there is just silence
]
SKIP_REASONS = ["aaj tabiyat theek hai, nahi leni", "doctor ne mana kiya tha"]

#: Two symptoms, one of them the escalation the demo turns on.
SYMPTOMS = [
    (4, "21:10", "سینے میں درد ہو رہا ہے", "emergency"),
    (9, "09:40", "thora sar chakra raha hai subah se", "routine"),
]


def outcome(story: str, index: int, total: int, rng: random.Random) -> str:
    """Which state one dose ended in. Deterministic per story, not random noise.

    A demo needs a shape the presenter can talk over: one medicine that goes
    well, one that is perfect, and one with a clear pattern in it.
    """
    if story == "perfect":
        return "TAKEN"

    if story == "steady":
        # Mostly taken, a few late, a handful missed, one declined.
        if index in (5, 13, 19, 23):
            return "MISSED"
        if index == 18:
            return "SKIPPED"
        if index in (3, 17):
            return "TAKEN_LATE"
        return "TAKEN"

    if story == "evenings_are_hard":
        # Every other dose is the evening one. That is the one being missed,
        # and it is the sentence the caretaker report is built to surface.
        evening = index % 2 == 1
        if evening and index in (3, 7, 11, 15, 21, 25):
            return "MISSED"
        if evening and index in (5, 17):
            return "TAKEN_LATE"
        return "TAKEN"

    return "TAKEN"


# --------------------------------------------------------------------------
# purge
# --------------------------------------------------------------------------


def purge() -> dict:
    """Remove a previous demo, in strict foreign-key order. Never anything else."""
    removed = {"patients": 0, "medicines": 0, "doses": 0, "reports": 0}

    with session_scope() as s:
        patients = s.exec(
            select(Patient).where(col(Patient.name).contains(TAG))
        ).all()
        patient_ids = [p.id for p in patients]
        family_ids = {p.family_id for p in patients}

        if patient_ids:
            medicines = s.exec(
                select(Medicine).where(col(Medicine.patient_id).in_(patient_ids))
            ).all()
            medicine_ids = [m.id for m in medicines]
            removed["medicines"] = len(medicine_ids)

            removed["reports"] = len(s.exec(
                select(Report).where(col(Report.patient_id).in_(patient_ids))
            ).all())
            removed["doses"] = len(s.exec(
                select(DoseEvent).where(col(DoseEvent.patient_id).in_(patient_ids))
            ).all())

            s.exec(delete(Report).where(col(Report.patient_id).in_(patient_ids)))
            s.exec(delete(SymptomReport).where(
                col(SymptomReport.patient_id).in_(patient_ids)))
            s.exec(delete(MessageLog).where(
                col(MessageLog.patient_id).in_(patient_ids)))
            s.exec(delete(DoseEvent).where(
                col(DoseEvent.patient_id).in_(patient_ids)))
            if medicine_ids:
                s.exec(delete(Schedule).where(
                    col(Schedule.medicine_id).in_(medicine_ids)))
                s.exec(delete(Medicine).where(col(Medicine.id).in_(medicine_ids)))
            s.exec(delete(Patient).where(col(Patient.id).in_(patient_ids)))
            removed["patients"] = len(patient_ids)
        s.commit()

    # A demo caretaker is only removed if this script created it and nobody
    # else is left in the family. A reference row naming them in confirmed_by
    # blocks the delete, so that link is cleared first.
    with session_scope() as s:
        carers = s.exec(
            select(Caretaker).where(col(Caretaker.name).contains(TAG))
        ).all()
        for carer in carers:
            s.exec(
                delete(MedicineReference)
                .where(MedicineReference.confirmed_by == carer.id)
                .where(col(MedicineReference.canonical_name).in_(
                    [m["name"].lower() for m in MEDICINES]))
            )
            s.delete(carer)
        s.commit()

    with session_scope() as s:
        for family_id in family_ids:
            has_people = s.exec(
                select(Patient).where(Patient.family_id == family_id)).first() \
                or s.exec(
                select(Caretaker).where(Caretaker.family_id == family_id)).first()
            if not has_people:
                family = s.get(Family, family_id)
                if family and TAG in (family.name or ""):
                    s.delete(family)
        s.commit()

    return removed


# --------------------------------------------------------------------------
# seed
# --------------------------------------------------------------------------


def find_caretaker(session, email: str | None) -> Caretaker | None:
    """The caretaker to hang the demo off.

    Attaching to a real signed-in account matters: the dashboard only ever
    shows one family's data, so a demo under a caretaker nobody signs in as is
    a demo nobody can see.
    """
    if email:
        return session.exec(
            select(Caretaker).where(Caretaker.email == email)).first()
    # Whoever signed in most recently is almost always the person demoing.
    return session.exec(
        select(Caretaker).order_by(col(Caretaker.created_at).desc())).first()


def seed(patient_name: str, phone: str, email: str | None,
         seed_value: int) -> dict:
    rng = random.Random(seed_value)
    # Asia/Karachi, not the server's date. The dashboard shows every date in
    # Karachi time, so seeding against a UTC "today" puts the demo's last day
    # in the wrong column for five hours every evening.
    today = datetime.now(settings.tz).date()
    start = today - timedelta(days=DAYS - 1)

    with session_scope() as s:
        carer = find_caretaker(s, email)
        if carer is None:
            family = Family(name=f"{TAG} Demo household")
            s.add(family)
            s.commit()
            s.refresh(family)
            carer = Caretaker(
                family_id=family.id, name=f"{TAG} Demo Caretaker",
                phone=DEMO_CARETAKER_NUMBER, relation="son",
                language="ur", verified=True)
            s.add(carer)
            s.commit()
            s.refresh(carer)
            created_caretaker = True
        else:
            created_caretaker = False
        carer_id, family_id = carer.id, carer.family_id
        carer_name = carer.name

        patient = Patient(
            family_id=family_id, name=f"{patient_name} {TAG}",
            whatsapp_number=phone, language="ur",
            opted_in=True, opted_in_at=datetime.now(timezone.utc))
        s.add(patient)
        s.commit()
        s.refresh(patient)
        patient_id = patient.id

    counts = {"medicines": 0, "doses": 0, "taken": 0, "late": 0,
              "missed": 0, "skipped": 0, "symptoms": 0}
    schedule_ids: list[str] = []

    for spec in MEDICINES:
        with session_scope() as s:
            reference = s.exec(
                select(MedicineReference).where(
                    MedicineReference.canonical_name == spec["name"].lower())
            ).first()
            if reference is None:
                reference = MedicineReference(
                    canonical_name=spec["name"].lower())
                s.add(reference)
            reference.purpose_ur = spec["purpose_ur"]
            reference.purpose_en = spec["purpose_en"]
            reference.food_rule = spec["food_rule"]
            reference.common_timing = spec["common_timing"]
            reference.source = "caretaker_edited"
            reference.confirmed = True
            reference.confirmed_by = carer_id
            reference.confirmed_at = datetime.now(timezone.utc)
            s.add(reference)
            s.commit()
            s.refresh(reference)
            reference_id = reference.id

            medicine = Medicine(
                patient_id=patient_id, reference_id=reference_id,
                name=spec["name"], strength=spec["strength"],
                form=spec["form"], active=True)
            s.add(medicine)
            s.commit()
            s.refresh(medicine)

            # Created INACTIVE on purpose. If the backend is running, its
            # ticker materialises doses for every active schedule once a
            # minute - and it will happily create today's dose in the gap
            # between this commit and the loop below, which then dies on the
            # idempotency_key unique constraint. `materialise_doses` filters
            # on `Schedule.active`, so an inactive schedule is invisible to it.
            # Switched on at the end, once every dose row is in place.
            schedule = Schedule(
                medicine_id=medicine.id, dose_times=spec["dose_times"],
                duration_days=DAYS, start_date=start,
                end_date=start + timedelta(days=DAYS - 1), active=False)
            s.add(schedule)
            s.commit()
            s.refresh(schedule)
            schedule_ids.append(schedule.id)
            counts["medicines"] += 1

            now = datetime.now(timezone.utc)
            index = 0
            for day in range(DAYS):
                for hhmm in spec["dose_times"]:
                    hour, minute = (int(x) for x in hhmm.split(":"))
                    local = datetime.combine(
                        start + timedelta(days=day), datetime.min.time(),
                        tzinfo=settings.tz).replace(hour=hour, minute=minute)
                    when = local.astimezone(timezone.utc)

                    # Anything still in the future is left SCHEDULED, exactly
                    # as the ticker would have it. Backdating a dose that has
                    # not happened is the one thing that would make the
                    # dashboard lie.
                    if when > now:
                        state, said, reason = "SCHEDULED", None, None
                    else:
                        state = outcome(spec["story"], index,
                                        DAYS * len(spec["dose_times"]), rng)
                        said, reason = words_for(state, rng)

                    dose = DoseEvent(
                        schedule_id=schedule.id, patient_id=patient_id,
                        idempotency_key=f"{schedule.id}:{when.isoformat()}",
                        scheduled_at=when, state=state,
                        sent_at=None if state == "SCHEDULED" else when,
                        responded_at=(None if state in ("SCHEDULED", "MISSED")
                                      else when + timedelta(
                                          minutes=rng.randint(1, 9))),
                        response_source=(None if state == "SCHEDULED" else "text"),
                        response_text=said, reason=reason,
                    )
                    s.add(dose)

                    if state != "SCHEDULED":
                        counts["doses"] += 1
                        counts[{"TAKEN": "taken", "TAKEN_LATE": "late",
                                "MISSED": "missed",
                                "SKIPPED": "skipped"}[state]] += 1
                    index += 1
            s.commit()

    # Every dose row is in place, so the ticker can have the schedules now.
    with session_scope() as s:
        for schedule_id in schedule_ids:
            schedule = s.get(Schedule, schedule_id)
            if schedule is not None:
                schedule.active = True
                s.add(schedule)
        s.commit()

    with session_scope() as s:
        for day, hhmm, text, severity in SYMPTOMS:
            # Deliberately NOT linked to a dose. The system does not know which
            # medicine a symptom relates to and invariant 8 forbids it guessing,
            # so an unlinked symptom is the truthful record - and it then shows
            # on every course running that week rather than on whichever
            # medicine happened to share the 08:00 slot.
            hour, minute = (int(x) for x in hhmm.split(":"))
            local = datetime.combine(start + timedelta(days=day),
                                     datetime.min.time(),
                                     tzinfo=settings.tz).replace(hour=hour,
                                                                 minute=minute)
            s.add(SymptomReport(
                patient_id=patient_id, dose_event_id=None,
                text_verbatim=text, language="ur", severity=severity,
                caretaker_alerted=True,
                reported_at=local.astimezone(timezone.utc)))
            counts["symptoms"] += 1
        s.commit()

    return {**counts, "patient_id": patient_id, "caretaker": carer_name,
            "created_caretaker": created_caretaker, "start": start,
            "end": start + timedelta(days=DAYS - 1)}


def words_for(state: str, rng: random.Random) -> tuple[str | None, str | None]:
    if state in ("TAKEN",):
        return rng.choice(TAKEN_REPLIES), None
    if state == "TAKEN_LATE":
        return rng.choice(LATE_REPLIES), None
    if state == "MISSED":
        reason = rng.choice(MISSED_REASONS)
        return (reason or None), (reason or None)
    if state == "SKIPPED":
        reason = rng.choice(SKIP_REASONS)
        return reason, reason
    return None, None


# --------------------------------------------------------------------------
# voice notes
# --------------------------------------------------------------------------


async def pregenerate(patient_id: str) -> int:
    """Give the seeded courses their Urdu voice notes.

    Needs the network. A failure is not fatal - reminders fall back to text,
    and `make seed` should not fail because a laptop is offline.
    """
    from app.voice.tts import pregenerate_for_medicine

    total = 0
    with session_scope() as s:
        medicine_ids = list(s.exec(
            select(Medicine.id).where(Medicine.patient_id == patient_id)).all())
    for medicine_id in medicine_ids:
        total += await pregenerate_for_medicine(medicine_id)
    return total


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed a demo-worthy MedNuskha database.")
    parser.add_argument("--name", default="Zubaida Bibi",
                        help="the patient's name (default: Zubaida Bibi)")
    parser.add_argument("--phone", default=DEMO_PATIENT_NUMBER,
                        help="patient's WhatsApp number, digits only. The "
                             "default cannot receive messages; pass a real "
                             "one only when you want a live demo.")
    parser.add_argument("--email", default=None,
                        help="attach to the caretaker with this email "
                             "(default: the most recently created one, which "
                             "is almost always whoever signed in last)")
    parser.add_argument("--seed", type=int, default=20260824,
                        help="random seed, so two runs look identical")
    parser.add_argument("--no-voice", action="store_true",
                        help="skip generating the Urdu voice notes")
    parser.add_argument("--purge-only", action="store_true",
                        help="delete the demo data and stop")
    args = parser.parse_args()

    if not settings.database_configured:
        print("DATABASE_URL is not set - copy .env.example to .env first.",
              file=sys.stderr)
        return 1

    print("clearing any previous demo...")
    removed = purge()
    if any(removed.values()):
        print(f"  removed {removed['patients']} patient(s), "
              f"{removed['medicines']} medicine(s), {removed['doses']} dose(s), "
              f"{removed['reports']} report(s)")
    else:
        print("  nothing to clear")

    if args.purge_only:
        print("\ndone.")
        return 0

    print(f"seeding {DAYS} days...")
    result = seed(args.name, args.phone, args.email, args.seed)

    if not args.no_voice:
        print("generating Urdu voice notes...")
        try:
            made = asyncio.run(pregenerate(result["patient_id"]))
            print(f"  {made} new file(s)")
        except Exception as exc:  # noqa: BLE001 - offline is not a failure
            print(f"  skipped ({exc}). Reminders will go out as text.")

    settled = result["taken"] + result["late"] + result["missed"] + result["skipped"]
    adherence = round((result["taken"] + result["late"]) / settled * 100) \
        if settled else 0

    print(f"""
  patient      {args.name} {TAG}   ({args.phone})
  caretaker    {result['caretaker']}{'  (created)' if result['created_caretaker'] else ''}
  course       {result['start']} to {result['end']}  ({DAYS} days)
  medicines    {result['medicines']}  -  {', '.join(m['name'] for m in MEDICINES)}
  doses        {settled} settled  ({result['taken']} taken, {result['late']} late,
               {result['missed']} missed, {result['skipped']} declined)  ->  {adherence}% adherence
  symptoms     {result['symptoms']}  (one flagged urgent)

Open http://localhost:3000 and sign in as {result['caretaker']}.
Both report buttons on any medicine card now have real numbers behind them.

To remove it again:  python scripts/seed_demo.py --purge-only
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
