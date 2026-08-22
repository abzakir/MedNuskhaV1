"""APScheduler jobs: dose materialisation, reminders, escalation, reports.

Runs in-process (AGENTS.md section 6 - not Celery, not Function Compute).

Two jobs:
  * every minute - materialise the next 24h of dose events from active
    schedules (idempotent on schedule_id + scheduled_at), then drive any dose
    whose reminder, follow-up or escalation is due.
  * once a day - generate course-end reports (Phase 6).

FOLLOWUP_MINUTES and ESCALATE_MINUTES always come from settings, never
hardcoded (section 14, Phase 2).

Startup is guarded: uvicorn --reload spawns two workers and an unguarded
APScheduler fires every job twice (section 17).
"""

from __future__ import annotations

_PHASE = "Phase 2 - the dose loop"


def start_scheduler() -> None:
    """Start the APScheduler instance, exactly once per process."""
    raise NotImplementedError(_PHASE)


def stop_scheduler() -> None:
    """Shut the scheduler down cleanly."""
    raise NotImplementedError(_PHASE)


def materialise_doses(hours_ahead: int = 24) -> int:
    """Create dose_event rows for the next `hours_ahead` from active schedules.

    Idempotent on dose_event.idempotency_key. Returns the number created.
    """
    raise NotImplementedError(_PHASE)


def tick() -> None:
    """One minute of work: send due reminders, follow up, escalate."""
    raise NotImplementedError(_PHASE)


def generate_course_end_reports() -> int:
    """Daily job: for every schedule past its end_date with no reports yet,
    generate the doctor and caretaker PDFs and message the caretaker."""
    raise NotImplementedError("Phase 6 - reports")
