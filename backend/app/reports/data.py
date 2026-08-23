"""Everything both reports need, gathered once.

The doctor report and the caretaker report describe the same course from two
angles, so they read the same numbers rather than each running their own
queries - two PDFs generated a second apart must never disagree about how many
doses were taken.

Nothing in here formats or interprets. The patient's own words come back
exactly as they were stored (invariant 8), and no field claims a dose was
observed being swallowed - only that the patient said so (invariant 11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, col, select

from app.config import settings
from app.db import session_scope
from app.models import (Caretaker, DoseEvent, Medicine, Patient, Schedule,
                        SymptomReport)

#: A dose the patient confirmed, one way or the other.
TAKEN_STATES = ("TAKEN", "TAKEN_LATE")
#: A dose whose outcome is settled. Doses still awaiting a reply are excluded
#: from every percentage - counting a dose due this evening as missed would
#: make every patient look worse than they are.
DECIDED_STATES = ("TAKEN", "TAKEN_LATE", "MISSED", "SKIPPED")


def _local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(settings.tz)


@dataclass
class MissedDose:
    """One dose that was not taken, with whatever the patient said about it."""

    when: datetime
    state: str
    #: The patient's own words, verbatim and untranslated. May be empty.
    said: str = ""


@dataclass
class Symptom:
    when: datetime
    #: Verbatim, never interpreted (invariant 8).
    text: str
    severity: str


@dataclass
class TimeOfDay:
    """How one dose time performed across the whole course."""

    hhmm: str
    taken: int
    missed: int

    @property
    def decided(self) -> int:
        return self.taken + self.missed

    @property
    def percent(self) -> int | None:
        return round(self.taken / self.decided * 100) if self.decided else None


@dataclass
class CourseReport:
    """One medicine's course, as both reports see it."""

    patient_name: str
    medicine_label: str

    start_date: date
    end_date: date
    duration_days: int
    dose_times: list[str]

    #: Counts by outcome.
    on_time: int = 0
    late: int = 0
    missed: int = 0
    skipped: int = 0
    pending: int = 0

    missed_log: list[MissedDose] = field(default_factory=list)
    symptoms: list[Symptom] = field(default_factory=list)
    by_time: list[TimeOfDay] = field(default_factory=list)

    #: Longest run of consecutive taken doses, and whether it is still running.
    best_streak: int = 0
    current_streak: int = 0

    generated_at: datetime = field(default_factory=lambda: datetime.now(settings.tz))

    # -- derived ---------------------------------------------------------

    @property
    def taken(self) -> int:
        return self.on_time + self.late

    @property
    def decided(self) -> int:
        return self.taken + self.missed + self.skipped

    @property
    def scheduled(self) -> int:
        return self.decided + self.pending

    @property
    def percent(self) -> int | None:
        """Adherence over settled doses only. None when nothing is settled."""
        return round(self.taken / self.decided * 100) if self.decided else None

    @property
    def hardest_time(self) -> TimeOfDay | None:
        """The dose time missed most often - None if nothing was ever missed."""
        candidates = [t for t in self.by_time if t.missed]
        if not candidates:
            return None
        return sorted(candidates, key=lambda t: (-t.missed, t.hhmm))[0]

    @property
    def is_complete(self) -> bool:
        return self.pending == 0


def _streaks(states: list[str]) -> tuple[int, int]:
    """Longest and trailing run of taken doses, in chronological order."""
    best = run = 0
    for state in states:
        if state in TAKEN_STATES:
            run += 1
            best = max(best, run)
        elif state in DECIDED_STATES:
            run = 0
        # A dose still awaiting a reply neither extends nor breaks a streak.
    return best, run


def _collect(session: Session, patient: Patient, medicine: Medicine,
             schedule: Schedule) -> CourseReport:
    doses = session.exec(
        select(DoseEvent)
        .where(DoseEvent.schedule_id == schedule.id)
        .order_by(col(DoseEvent.scheduled_at))
    ).all()

    label = f"{medicine.name} {medicine.strength}".strip() \
        if medicine.strength else medicine.name

    report = CourseReport(
        patient_name=patient.name,
        medicine_label=label,
        start_date=schedule.start_date,
        end_date=schedule.end_date,
        duration_days=schedule.duration_days,
        dose_times=list(schedule.dose_times or []),
    )

    per_time: dict[str, list[int]] = {t: [0, 0] for t in report.dose_times}

    for dose in doses:
        when = _local(dose.scheduled_at)
        hhmm = when.strftime("%H:%M") if when else "?"

        if dose.state == "TAKEN":
            report.on_time += 1
        elif dose.state == "TAKEN_LATE":
            report.late += 1
        elif dose.state == "MISSED":
            report.missed += 1
        elif dose.state == "SKIPPED":
            report.skipped += 1
        else:
            report.pending += 1

        if dose.state in ("MISSED", "SKIPPED"):
            # reason is the stated reason; response_text is whatever they sent.
            said = (dose.reason or dose.response_text or "").strip()
            report.missed_log.append(
                MissedDose(when=when, state=dose.state, said=said))

        slot = per_time.setdefault(hhmm, [0, 0])
        if dose.state in TAKEN_STATES:
            slot[0] += 1
        elif dose.state in ("MISSED", "SKIPPED"):
            slot[1] += 1

    report.by_time = [TimeOfDay(hhmm=t, taken=v[0], missed=v[1])
                      for t, v in sorted(per_time.items())]
    report.best_streak, report.current_streak = _streaks([d.state for d in doses])

    dose_ids = [d.id for d in doses]
    if dose_ids:
        symptoms = session.exec(
            select(SymptomReport)
            .where(col(SymptomReport.dose_event_id).in_(dose_ids))
            .order_by(col(SymptomReport.reported_at))
        ).all()
    else:
        symptoms = []

    # Symptoms reported without a dose attached still belong to the course if
    # they fall inside its dates - a patient rarely replies to the reminder.
    window_start = datetime.combine(schedule.start_date, datetime.min.time(),
                                    tzinfo=settings.tz).astimezone(timezone.utc)
    window_end = (datetime.combine(schedule.end_date, datetime.min.time(),
                                   tzinfo=settings.tz)
                  + timedelta(days=1)).astimezone(timezone.utc)
    loose = session.exec(
        select(SymptomReport)
        .where(SymptomReport.patient_id == patient.id)
        .where(col(SymptomReport.dose_event_id).is_(None))
        .where(SymptomReport.reported_at >= window_start)
        .where(SymptomReport.reported_at < window_end)
        .order_by(col(SymptomReport.reported_at))
    ).all()

    seen: set[str] = set()
    for row in list(symptoms) + list(loose):
        if row.id in seen:
            continue
        seen.add(row.id)
        report.symptoms.append(Symptom(when=_local(row.reported_at),
                                       text=row.text_verbatim,
                                       severity=row.severity))
    report.symptoms.sort(key=lambda s: s.when)

    return report


def for_course(patient_id: str, medicine_id: str) -> CourseReport:
    """Gather one medicine's course. Raises LookupError if it does not exist."""
    with session_scope() as session:
        patient = session.get(Patient, patient_id)
        if patient is None:
            raise LookupError(f"no patient {patient_id}")

        medicine = session.get(Medicine, medicine_id)
        if medicine is None or medicine.patient_id != patient_id:
            raise LookupError(f"no medicine {medicine_id} for patient {patient_id}")

        schedule = session.exec(
            select(Schedule)
            .where(Schedule.medicine_id == medicine_id)
            .order_by(col(Schedule.created_at).desc())
        ).first()
        if schedule is None:
            raise LookupError(f"medicine {medicine_id} has no schedule")

        return _collect(session, patient, medicine, schedule)


def latest_medicine_id(patient_id: str) -> str | None:
    """The medicine to report on when the caller did not name one."""
    with session_scope() as session:
        row = session.exec(
            select(Medicine.id)
            .where(Medicine.patient_id == patient_id)
            .order_by(col(Medicine.active).desc(), col(Medicine.created_at).desc())
        ).first()
        return row


def caretakers_of(patient_id: str) -> list[dict]:
    """Who should be told a report exists."""
    with session_scope() as session:
        patient = session.get(Patient, patient_id)
        if patient is None:
            return []
        rows = session.exec(
            select(Caretaker).where(Caretaker.family_id == patient.family_id)
        ).all()
        return [{"id": c.id, "name": c.name, "phone": c.phone,
                 "language": c.language} for c in rows if c.phone]
