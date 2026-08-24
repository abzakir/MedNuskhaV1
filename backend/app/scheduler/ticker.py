"""APScheduler jobs: dose materialisation, reminders, follow-ups, escalation.

Runs in-process (AGENTS.md section 6 - not Celery, not Function Compute).

Two jobs:
  * every minute - materialise the next 24h of dose events from active
    schedules, then drive any dose whose reminder, follow-up or escalation is
    due.
  * once a day - course-end reports (Phase 6).

FOLLOWUP_MINUTES and ESCALATE_MINUTES always come from settings, never
hardcoded (section 14, Phase 2). Both are measured from `sent_at`.

Start-up is guarded twice (section 17). A module flag stops a double start
inside one process, and a Postgres advisory lock stops a second process -
another uvicorn worker, or a teammate running `dev.ps1` against the same
Supabase project - from firing every reminder a second time.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, time, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, select

from app.config import settings
from app.db import get_engine, session_scope
from app.i18n import strings
from app.models import (  # noqa: F401
    Caretaker,
    DoseEvent,
    Medicine,
    MedicineReference,
    Patient,
    Schedule,
    new_id,
)
from app.scheduler import state_machine as sm
from app.whatsapp import client as wa

log = logging.getLogger(__name__)

#: Arbitrary but fixed: identifies *this* application's ticker lock.
_LOCK_KEY = 8_23_2026

#: A dose older than this when we first see it is treated as already missed
#: rather than reminded. Without it, a server that was down for an hour wakes
#: up and fires a burst of stale reminders at a 68-year-old.
_STALE_GRACE = timedelta(minutes=5)

_scheduler: AsyncIOScheduler | None = None
_lock_conn = None


# --------------------------------------------------------------------------
# time helpers - the system runs entirely in Asia/Karachi (section 4)
# --------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def local_today() -> date:
    return _now().astimezone(settings.tz).date()


def to_utc(day: date, hhmm: str) -> datetime:
    """Turn a schedule's local "HH:MM" on a local date into a UTC instant."""
    hour, minute = (int(part) for part in hhmm.split(":", 1))
    local = datetime.combine(day, time(hour, minute), tzinfo=settings.tz)
    return local.astimezone(timezone.utc)


def local_hour_label(when: datetime) -> str:
    """"8" for both 08:00 and 20:00 - how the reminder reads aloud in Urdu."""
    return str(int(when.astimezone(settings.tz).strftime("%I")))


def _clean_var(value: str | None, fallback: str = "-") -> str:
    """Make a string safe as a WhatsApp template parameter.

    Meta rejects an empty parameter outright, and also rejects newlines, tabs
    and runs of four or more spaces. A template that fails this way fails at
    send time, on a real patient's dose.
    """
    cleaned = re.sub(r"[\r\n\t]+", " ", (value or "").strip())
    cleaned = re.sub(r" {4,}", "   ", cleaned)
    return cleaned or fallback


# --------------------------------------------------------------------------
# materialisation
# --------------------------------------------------------------------------


def materialise_doses(hours_ahead: int = 24) -> int:
    """Create dose_event rows for the next `hours_ahead` from active schedules.

    Idempotent on dose_event.idempotency_key via ON CONFLICT DO NOTHING, so
    running this every minute is free and a restart never duplicates a dose
    (invariant 5).

    `schedule.end_date` is INCLUSIVE - the last day a dose is due (SCHEMA.md).
    """
    horizon = _now() + timedelta(hours=hours_ahead)
    today = local_today()
    created = 0

    with session_scope() as session:
        rows = session.exec(
            select(Schedule, Medicine)
            .join(Medicine, Medicine.id == Schedule.medicine_id)
            .join(Patient, Patient.id == Medicine.patient_id)
            .where(Schedule.active == True)          # noqa: E712
            .where(Medicine.active == True)          # noqa: E712
            .where(Patient.opted_in == True)         # noqa: E712
            .where(Patient.stopped == False)         # noqa: E712
            .where(Schedule.end_date >= today)
        ).all()

        payload: list[dict] = []
        for schedule, medicine in rows:
            day = max(schedule.start_date, today)
            while day <= schedule.end_date:
                for hhmm in schedule.dose_times or []:
                    try:
                        when = to_utc(day, hhmm)
                    except (ValueError, AttributeError):
                        log.warning("schedule %s has a bad dose time %r",
                                    schedule.id, hhmm)
                        continue
                    if when > horizon:
                        continue
                    payload.append({
                        "id": new_id(),
                        "schedule_id": schedule.id,
                        "patient_id": medicine.patient_id,
                        "scheduled_at": when,
                        "idempotency_key": f"{schedule.id}:{when.isoformat()}",
                        "state": "SCHEDULED",
                    })
                day += timedelta(days=1)

        if payload:
            stmt = (
                pg_insert(DoseEvent.__table__)
                .values(payload)
                .on_conflict_do_nothing(index_elements=["idempotency_key"])
                # RETURNING, not rowcount: psycopg reports -1 for a multi-row
                # upsert, and this count is logged - a wrong number here sends
                # someone debugging in the wrong direction at 2am.
                .returning(DoseEvent.__table__.c.id)
            )
            created = len(session.execute(stmt).fetchall())
            session.commit()

    if created:
        log.info("materialised %d dose events", created)
    return created


# --------------------------------------------------------------------------
# context for message copy
# --------------------------------------------------------------------------


def _context(session, dose: DoseEvent) -> dict | None:
    """Everything the message copy needs for one dose."""
    schedule = session.get(Schedule, dose.schedule_id)
    if schedule is None:
        return None
    medicine = session.get(Medicine, schedule.medicine_id)
    patient = session.get(Patient, dose.patient_id)
    if medicine is None or patient is None:
        return None

    label = medicine.name
    if medicine.strength:
        label = f"{medicine.name} {medicine.strength}"

    # Invariant 9: only a CONFIRMED reference row may be repeated to a
    # patient. An unconfirmed AI draft is never spoken aloud.
    note = None
    if medicine.reference_id:
        ref = session.get(MedicineReference, medicine.reference_id)
        if ref is not None and ref.confirmed:
            note = ref.food_rule

    caretakers = session.exec(
        select(Caretaker).where(Caretaker.family_id == patient.family_id)
    ).all()

    return {
        "patient_name": patient.name,
        "patient_number": patient.whatsapp_number,
        "patient_language": patient.language,
        "medicine_label": label,
        "food_note": note,
        "caretakers": [{"id": c.id, "name": c.name, "phone": c.phone,
                        "relation": c.relation, "language": c.language}
                       for c in caretakers],
    }


def _load(dose_id: str) -> tuple[DoseEvent, dict] | None:
    with session_scope() as session:
        dose = session.get(DoseEvent, dose_id)
        if dose is None:
            return None
        ctx = _context(session, dose)
        if ctx is None:
            log.warning("dose %s has no usable context - skipping", dose_id)
            return None
        session.expunge(dose)
        return dose, ctx


# --------------------------------------------------------------------------
# the three outbound moments
# --------------------------------------------------------------------------


async def send_reminder(dose_id: str) -> bool:
    """SCHEDULED -> SENT -> AWAITING_REPLY, with the dose_reminder template."""
    loaded = await asyncio.to_thread(_load, dose_id)
    if loaded is None:
        return False
    dose, ctx = loaded

    # Claim before sending (invariant 5). See mark_sent's docstring.
    if not await asyncio.to_thread(sm.mark_sent, dose_id):
        return False

    try:
        await wa.send_template(
            to=ctx["patient_number"],
            template="dose_reminder",
            lang=ctx["patient_language"],
            body_vars=[
                _clean_var(ctx["patient_name"], "Ji"),
                _clean_var(local_hour_label(dose.scheduled_at), "abhi"),
                _clean_var(ctx["medicine_label"], "dawai"),
                _clean_var(ctx["food_note"], "Shukriya."),
            ],
            button_payloads=[f"TAKEN:{dose_id}", f"LATER:{dose_id}"],
        )
    except Exception as exc:  # noqa: BLE001 - a failed send must not stop the tick
        log.error("dose %s: reminder send FAILED: %s", dose_id, exc)
        return False

    await _attach_voice_note(dose_id, ctx["patient_number"])

    await asyncio.to_thread(sm.mark_awaiting_reply, dose_id)
    return True


async def _attach_voice_note(dose_id: str, to: str) -> bool:
    """Send the pre-generated voice note that goes with a reminder.

    Reads only - section 3.4 forbids synthesising here, and the ticker runs
    every minute. A dose with no cached audio simply goes out as text, which
    is what happens for anything scheduled before Phase 5 landed.

    Sent AFTER the text on purpose: the words are on screen while the voice
    plays, and if the audio send fails the patient has already been reminded.
    """
    if not settings.voice_notes_enabled:
        return False
    try:
        from app.voice import tts

        audio = await asyncio.to_thread(tts.audio_for, dose_id)
        if not audio:
            return False
        await wa.send_voice(to, audio)
        return True
    except Exception as exc:  # noqa: BLE001 - the reminder itself already went
        log.warning("dose %s: voice note not sent (%s)", dose_id, exc)
        return False


async def send_followup(dose_id: str) -> bool:
    """-> REMINDED_AGAIN, with the gentler dose_followup template."""
    loaded = await asyncio.to_thread(_load, dose_id)
    if loaded is None:
        return False
    _, ctx = loaded

    if not await asyncio.to_thread(sm.mark_reminded_again, dose_id):
        return False

    try:
        await wa.send_template(
            to=ctx["patient_number"],
            template="dose_followup",
            lang=ctx["patient_language"],
            body_vars=[
                _clean_var(ctx["patient_name"], "Ji"),
                _clean_var(ctx["medicine_label"], "dawai"),
            ],
            button_payloads=[f"TAKEN:{dose_id}", f"LATER:{dose_id}"],
        )
    except Exception as exc:  # noqa: BLE001
        log.error("dose %s: follow-up send FAILED: %s", dose_id, exc)
        return False

    # The follow-up says something different from the reminder, so it needs
    # its own line - but it is still read from the cache, never synthesised.
    await _attach_followup_voice(dose_id, ctx)
    return True


async def _attach_followup_voice(dose_id: str, ctx: dict) -> bool:
    """The gentler second line, if it happens to be cached already.

    Pre-generation covers reminders. A follow-up only reaches a patient who
    has not answered, so its audio is generated the first time that happens
    for a given medicine and then reused - off the reminder path, in a dose
    that has already been sent.
    """
    if not settings.voice_notes_enabled:
        return False
    try:
        from app.i18n import strings as _s
        from app.voice import store, tts

        line = _s.spoken("dose_followup", medicine=ctx["medicine_label"])
        if not line:
            return False

        key = store.key_for(line)
        audio = await asyncio.to_thread(store.get, key)
        if audio is None:
            # Not on the reminder path: this dose was reminded 15 minutes ago.
            if await tts.ensure_cached(line) is None:
                return False
            audio = await asyncio.to_thread(store.get, key)
        if not audio:
            return False

        await wa.send_voice(ctx["patient_number"], audio)
        return True
    except Exception as exc:  # noqa: BLE001 - the follow-up text already went
        log.warning("dose %s: follow-up voice not sent (%s)", dose_id, exc)
        return False


async def escalate(dose_id: str) -> bool:
    """-> MISSED, and tell the caretaker. The moment that sells the product."""
    loaded = await asyncio.to_thread(_load, dose_id)
    if loaded is None:
        return False
    dose, ctx = loaded

    if not await asyncio.to_thread(sm.mark_missed, dose_id):
        return False

    if not ctx["caretakers"]:
        log.warning("dose %s missed but the family has no caretaker to alert",
                    dose_id)
        return False

    reached = False
    for caretaker in ctx["caretakers"]:
        try:
            await wa.send_template(
                to=caretaker["phone"],
                template="caretaker_alert",
                lang=caretaker.get("language", "ur"),
                body_vars=[
                    _clean_var(ctx["patient_name"], "Patient"),
                    _clean_var(local_hour_label(dose.scheduled_at), "aaj"),
                    _clean_var(ctx["medicine_label"], "dawai"),
                ],
            )
            reached = True
        except Exception as exc:  # noqa: BLE001 - try the next caretaker
            log.error("dose %s: caretaker alert to %s FAILED: %s",
                      dose_id, caretaker["phone"], exc)

    if reached:
        await asyncio.to_thread(sm.mark_caretaker_alerted, dose_id)
    return reached


async def notify_late_resolution(dose_id: str) -> None:
    """Tell the caretaker a missed dose was confirmed after all (section 4.8).

    Free-form, not a template: the caretaker was messaged minutes ago by the
    escalation, so the 24-hour window is open.
    """
    loaded = await asyncio.to_thread(_load, dose_id)
    if loaded is None:
        return
    _, ctx = loaded

    for caretaker in ctx["caretakers"]:
        body = (f"{ctx['patient_name']} ne abhi {ctx['medicine_label']} "
                f"lene ki tasdeeq kar di hai - thori der se. "
                f"Ye aap ki agli report mein bhi likha jayega.")
        try:
            await wa.send_text(caretaker["phone"], body)
        except Exception as exc:  # noqa: BLE001
            log.error("dose %s: late-resolution note to %s failed: %s",
                      dose_id, caretaker["phone"], exc)


# --------------------------------------------------------------------------
# the tick
# --------------------------------------------------------------------------


def _due_reminders() -> tuple[list[str], list[str]]:
    """(doses to remind now, doses too stale to remind and already missed)."""
    now = _now()
    fresh, stale = [], []
    with session_scope() as session:
        rows = session.exec(
            select(DoseEvent)
            .where(DoseEvent.state == "SCHEDULED")
            .where(DoseEvent.scheduled_at <= now)
            .order_by(DoseEvent.scheduled_at)
        ).all()
        window = timedelta(minutes=settings.escalate_minutes) + _STALE_GRACE
        for dose in rows:
            due = dose.scheduled_at
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            (stale if now - due > window else fresh).append(dose.id)
    return fresh, stale


def _due_followups() -> list[str]:
    cutoff = _now() - timedelta(minutes=settings.followup_minutes)
    with session_scope() as session:
        rows = session.exec(
            select(DoseEvent)
            .where(col(DoseEvent.state).in_(("SENT", "AWAITING_REPLY")))
            .where(DoseEvent.sent_at <= cutoff)
        ).all()
        return [d.id for d in rows]


def _due_escalations() -> list[str]:
    cutoff = _now() - timedelta(minutes=settings.escalate_minutes)
    with session_scope() as session:
        rows = session.exec(
            select(DoseEvent)
            .where(DoseEvent.state == "REMINDED_AGAIN")
            .where(DoseEvent.sent_at <= cutoff)
        ).all()
        return [d.id for d in rows]


async def course_end_reports() -> dict:
    """Once a day: generate both reports for any course that has ended.

    A course is finished when its INCLUSIVE `end_date` is in the past. For each
    one that has no `course_end` reports yet, both PDFs are generated, archived
    and the caretaker is sent the two links.

    Idempotent by construction: the `report` rows are the record of what has
    already been sent, so a second run the next morning finds nothing to do.
    Generating never happens twice for the same course even if the message
    fails, which is the right way round - a caretaker who gets no message can
    still open the report from the dashboard, whereas duplicate PDFs of a
    finished course arriving daily would be noise.
    """
    from app.reports import service, storage

    counts = {"courses": 0, "reports": 0, "messaged": 0}
    try:
        courses = await asyncio.to_thread(service.finished_courses)
    except Exception as exc:  # noqa: BLE001 - never take the scheduler down
        log.exception("could not look for finished courses: %s", exc)
        return counts

    for course in courses:
        patient_id = course["patient_id"]
        medicine_id = course["medicine_id"]
        counts["courses"] += 1

        carers = await asyncio.to_thread(data_caretakers, patient_id)
        lang = (carers[0].get("language") if carers else None) or "en"

        links: dict[str, str] = {}
        try:
            for kind in course["missing"]:
                row, _ = await asyncio.to_thread(
                    service.generate, kind, patient_id, medicine_id,
                    trigger="course_end", lang=lang)
                links[kind] = storage.share_url(row.id)
                counts["reports"] += 1
        except Exception as exc:  # noqa: BLE001 - one bad course, not all
            log.exception("could not generate reports for medicine %s: %s",
                          medicine_id, exc)
            continue

        # A kind that already existed has no fresh link, so reuse the old row.
        for kind in ("doctor", "caretaker"):
            if kind not in links:
                existing = await asyncio.to_thread(
                    _latest_report_id, patient_id, medicine_id, kind)
                if existing:
                    links[kind] = storage.share_url(existing)

        if not carers:
            log.warning("course %s finished but the patient has no caretaker "
                        "with a phone number", medicine_id)
            continue

        context = await asyncio.to_thread(_course_context, patient_id, medicine_id)
        for carer in carers:
            body = strings.t(
                "report_ready", carer.get("language") or "en",
                patient=context["patient"], medicine=context["medicine"],
                doctor_url=links.get("doctor", "-"),
                caretaker_url=links.get("caretaker", "-"))
            try:
                await wa.send_text(carer["phone"], body)
                counts["messaged"] += 1
            except Exception as exc:  # noqa: BLE001 - try the next caretaker
                log.error("could not send the report link to %s: %s",
                          carer["phone"], exc)

    if any(counts.values()):
        log.info("course-end reports: %s", counts)
    return counts


def data_caretakers(patient_id: str) -> list[dict]:
    from app.reports import data as report_data
    return report_data.caretakers_of(patient_id)


def _latest_report_id(patient_id: str, medicine_id: str, kind: str) -> str | None:
    from app.models import Report
    with session_scope() as session:
        return session.exec(
            select(Report.id)
            .where(Report.patient_id == patient_id)
            .where(Report.medicine_id == medicine_id)
            .where(Report.kind == kind)
            .order_by(col(Report.generated_at).desc())
        ).first()


def _course_context(patient_id: str, medicine_id: str) -> dict:
    with session_scope() as session:
        patient = session.get(Patient, patient_id)
        medicine = session.get(Medicine, medicine_id)
        label = medicine.name if medicine else "the medicine"
        if medicine and medicine.strength:
            label = f"{medicine.name} {medicine.strength}"
        return {"patient": patient.name if patient else "your family member",
                "medicine": label}


async def tick() -> dict:
    """One minute of work. Safe to run concurrently with itself."""
    counts = {"materialised": 0, "reminded": 0, "followed_up": 0,
              "escalated": 0, "stale_missed": 0}
    try:
        counts["materialised"] = await asyncio.to_thread(materialise_doses)

        fresh, stale = await asyncio.to_thread(_due_reminders)
        for dose_id in stale:
            log.warning("dose %s is past the escalation window before it was "
                        "ever sent - marking MISSED without reminding", dose_id)
            if await asyncio.to_thread(sm.mark_missed, dose_id):
                counts["stale_missed"] += 1
        for dose_id in fresh:
            if await send_reminder(dose_id):
                counts["reminded"] += 1

        for dose_id in await asyncio.to_thread(_due_followups):
            if await send_followup(dose_id):
                counts["followed_up"] += 1

        for dose_id in await asyncio.to_thread(_due_escalations):
            if await escalate(dose_id):
                counts["escalated"] += 1

    except Exception as exc:  # noqa: BLE001 - the ticker must never die
        log.exception("tick failed: %s", exc)

    if any(counts.values()):
        log.info("tick: %s", counts)
    return counts


# --------------------------------------------------------------------------
# lifecycle
# --------------------------------------------------------------------------


def _acquire_lock() -> bool:
    """Exactly one process may run the ticker (section 17).

    A Postgres session-level advisory lock is held for as long as the
    connection stays open, and is released automatically if the process dies -
    which a flag in memory can never manage.
    """
    global _lock_conn
    try:
        conn = get_engine().connect()
        got = conn.execute(
            sql_text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}
        ).scalar()
        if got:
            _lock_conn = conn
            return True
        conn.close()
        return False
    except Exception as exc:  # noqa: BLE001
        log.error("could not take the scheduler lock: %s", exc)
        return False


def _release_lock() -> None:
    global _lock_conn
    if _lock_conn is None:
        return
    try:
        _lock_conn.execute(sql_text("SELECT pg_advisory_unlock(:k)"),
                           {"k": _LOCK_KEY})
        _lock_conn.close()
    except Exception:  # noqa: BLE001
        pass
    _lock_conn = None


def start_scheduler() -> bool:
    """Start the scheduler, at most once per process and once per database."""
    global _scheduler

    if _scheduler is not None:
        log.debug("scheduler already running in this process")
        return False

    if not settings.database_configured:
        log.warning("scheduler not started - no DATABASE_URL")
        return False

    if not _acquire_lock():
        log.warning("scheduler NOT started - another process holds the lock. "
                    "This is the guard against uvicorn --reload or a second "
                    "worker firing every reminder twice.")
        return False

    _scheduler = AsyncIOScheduler(timezone=str(settings.tz))
    _scheduler.add_job(tick, "interval", minutes=1, id="dose_tick",
                       max_instances=1, coalesce=True, misfire_grace_time=55)
    # Phase 6. Early morning local time: the course ended yesterday, and a
    # caretaker would rather find the report waiting than be pinged at 3am.
    _scheduler.add_job(course_end_reports, "cron", hour=8, minute=5,
                       id="course_end_reports", max_instances=1,
                       coalesce=True, misfire_grace_time=3600)
    _scheduler.start()

    log.info("scheduler started - followup=%dmin escalate=%dmin tz=%s",
             settings.followup_minutes, settings.escalate_minutes,
             settings.timezone)
    return True


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("scheduler stopped")
    _release_lock()


def is_running() -> bool:
    return _scheduler is not None
