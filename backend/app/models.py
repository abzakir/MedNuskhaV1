"""All database tables - AGENTS.md section 8. FROZEN at the end of Phase 0.

Eleven tables: family, caretaker, patient, medicine, schedule, dose_event,
message_log, symptom_report, prescription, medicine_reference, report.

Conventions used throughout:

* Primary keys are UUID4 strings, matching the `str` ids in the section 9
  contracts.
* Every timestamp is timezone-aware and stored in UTC. Anything a human reads
  is converted to `settings.tz` (Asia/Karachi) at the edge, never in the DB.
* State/kind columns are plain text with the allowed values listed in the
  module constants. No Postgres enums - we have no migrations tooling
  (section 4), and a text column is the one thing that survives a schema tweak.

Column-level documentation lives in SCHEMA.md.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Column, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_column(nullable: bool = True) -> Column:
    """JSONB on Postgres.

    Declared per-field rather than as a module constant because a SQLAlchemy
    Column object cannot be shared between two models.
    """
    return Column(JSONB, nullable=nullable)


# --------------------------------------------------------------------------
# allowed values (documented in code, not enforced by the DB)
# --------------------------------------------------------------------------

LANGUAGES = ("ur", "en")

#: dose_event.state - AGENTS.md section 8.
#: Transitions live ONLY in scheduler/state_machine.py.
DOSE_STATES = (
    "SCHEDULED",
    "SENT",
    "AWAITING_REPLY",
    "REMINDED_AGAIN",
    "TAKEN",
    "TAKEN_LATE",
    "MISSED",
    "SKIPPED",
)

#: States that end the escalation chain - no further reminders are ever sent.
DOSE_TERMINAL_STATES = ("TAKEN", "TAKEN_LATE", "MISSED", "SKIPPED")

MESSAGE_DIRECTIONS = ("in", "out")
MESSAGE_KINDS = ("text", "template", "button", "interactive", "audio", "image", "other")
RESPONSE_SOURCES = ("button", "text", "voice")
REFERENCE_SOURCES = ("ai_fetched", "caretaker_edited")
REPORT_KINDS = ("doctor", "caretaker")
REPORT_TRIGGERS = ("course_end", "on_demand")
PRESCRIPTION_STATES = ("pending", "confirmed", "discarded")
SYMPTOM_SEVERITIES = ("routine", "emergency")


# --------------------------------------------------------------------------
# 1. family
# --------------------------------------------------------------------------


class Family(SQLModel, table=True):
    """A household.

    Caretakers and patients both hang off one family, which is how multiple
    caretakers link to one patient (section 4.10) without a join table.
    """

    __tablename__ = "family"

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


# --------------------------------------------------------------------------
# 2. caretaker
# --------------------------------------------------------------------------


class Caretaker(SQLModel, table=True):
    """The person who registers on the dashboard and receives escalations.

    `relation` is free text ("son", "daughter", "spouse", "caregiver") and is
    used in message copy - "aap ke bete ne..." - as well as on the dashboard.
    """

    __tablename__ = "caretaker"

    id: str = Field(default_factory=new_id, primary_key=True)
    family_id: str = Field(foreign_key="family.id", index=True)
    name: str
    #: Nullable since 2026-08-23: a caretaker now registers with an email and
    #: supplies their WhatsApp number afterwards, so the row exists before the
    #: number does. Still unique when present - Postgres allows many NULLs
    #: under a unique index.
    phone: str | None = Field(
        default=None,
        index=True,
        unique=True,
        description="digits only, no + and no leading zero, e.g. 923001234567",
    )
    relation: str = Field(default="caregiver")
    language: str = Field(default="ur", description="one of LANGUAGES")

    #: Added 2026-08-23. Section 4.1 assumed phone + OTP; the product now signs
    #: caretakers in with email or Google through Supabase Auth, so we need
    #: somewhere to put the identity. Both nullable, so existing rows and the
    #: dev bypass keep working. See PROJECT_LOG.md.
    email: str | None = Field(default=None, index=True)
    #: Supabase Auth user id (the `sub` claim). UNIQUE - the dashboard
    #: fires several requests at once on load, and without this they each
    #: create their own caretaker AND their own family.
    auth_user_id: str | None = Field(default=None, index=True, unique=True)

    # phone + OTP signup (section 4.1); a dev bypass is acceptable.
    otp_code: str | None = Field(default=None)
    otp_expires_at: datetime | None = Field(default=None)
    verified: bool = Field(default=False)

    created_at: datetime = Field(default_factory=utcnow, nullable=False)


# --------------------------------------------------------------------------
# 3. patient
# --------------------------------------------------------------------------


class Patient(SQLModel, table=True):
    """The elderly person receiving reminders. Never logs in (section 3.1)."""

    __tablename__ = "patient"

    id: str = Field(default_factory=new_id, primary_key=True)
    family_id: str = Field(foreign_key="family.id", index=True)
    name: str
    whatsapp_number: str = Field(
        index=True, unique=True, description="digits only, e.g. 923001234567"
    )
    language: str = Field(default="ur", description="one of LANGUAGES")

    #: Set true only after the patient replies HAAN to `patient_optin`
    #: (section 4.4). No reminder is sent to a patient who has not opted in.
    opted_in: bool = Field(default=False)
    opted_in_at: datetime | None = Field(default=None)

    #: Patient sent STOP. Everything outbound halts and the caretaker is told.
    stopped: bool = Field(default=False)

    created_at: datetime = Field(default_factory=utcnow, nullable=False)


# --------------------------------------------------------------------------
# 4. medicine_reference
# --------------------------------------------------------------------------


class MedicineReference(SQLModel, table=True):
    """Cache of AI-fetched, caretaker-confirmed medicine knowledge.

    Sections 8 and 5.9. One row per unique medicine name across the whole
    system. A row is created by `agent.knowledge.fetch_draft` as a DRAFT
    (`confirmed = False`) and is invisible to patients until a caretaker
    confirms it on the dashboard. The agent may only ever read rows where
    `confirmed = True`.
    """

    __tablename__ = "medicine_reference"

    id: str = Field(default_factory=new_id, primary_key=True)
    canonical_name: str = Field(index=True, unique=True)
    aliases: list[str] | None = Field(default=None, sa_column=_json_column())

    purpose_ur: str | None = Field(default=None)
    purpose_en: str | None = Field(default=None)
    food_rule: str | None = Field(default=None, description="e.g. khane ke baad")
    common_timing: str | None = Field(default=None, description="e.g. subah aur raat")

    source: str = Field(default="ai_fetched", description="one of REFERENCE_SOURCES")
    confirmed: bool = Field(default=False, index=True)
    confirmed_by: str | None = Field(default=None, foreign_key="caretaker.id")

    fetched_at: datetime = Field(default_factory=utcnow, nullable=False)
    confirmed_at: datetime | None = Field(default=None)


# --------------------------------------------------------------------------
# 5. medicine
# --------------------------------------------------------------------------


class Medicine(SQLModel, table=True):
    """One medicine prescribed to one patient.

    A patient may have several active at once, each with its own schedule and
    its own independent tenure (section 4.3).
    """

    __tablename__ = "medicine"

    id: str = Field(default_factory=new_id, primary_key=True)
    patient_id: str = Field(foreign_key="patient.id", index=True)

    #: Links to the shared, caretaker-confirmed knowledge row. Null only if the
    #: medicine was added before any reference row existed.
    reference_id: str | None = Field(default=None, foreign_key="medicine_reference.id")

    name: str

    #: Always included in patient-facing copy (section 11: "names the medicine
    #: and strength every time").
    strength: str | None = Field(default=None, description="e.g. 500mg")
    form: str | None = Field(default=None, description="tablet / syrup / capsule")
    notes: str | None = Field(default=None)

    active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


# --------------------------------------------------------------------------
# 6. schedule
# --------------------------------------------------------------------------


class Schedule(SQLModel, table=True):
    """One row per medicine's course (section 8).

    `end_date` is INCLUSIVE - it is the last day a dose is due. A 7-day course
    starting 2026-08-22 has `end_date = 2026-08-28`. See the Session 1 entry in
    PROJECT_LOG.md for why this differs from the literal formula in section 8.
    """

    __tablename__ = "schedule"

    id: str = Field(default_factory=new_id, primary_key=True)
    medicine_id: str = Field(foreign_key="medicine.id", index=True)

    #: Local Asia/Karachi wall-clock times as "HH:MM", e.g. ["08:00", "20:00"].
    dose_times: list[str] = Field(sa_column=_json_column(nullable=False))

    duration_days: int = Field(description="tenure: 7 / 14 / 30 or custom (section 4.3)")
    start_date: date
    end_date: date = Field(index=True, description="inclusive last dose day")

    active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


# --------------------------------------------------------------------------
# 7. dose_event
# --------------------------------------------------------------------------


class DoseEvent(SQLModel, table=True):
    """One scheduled dose and everything that happened to it.

    `idempotency_key` is "{schedule_id}:{scheduled_at as ISO-8601 UTC}" and is
    UNIQUE. It is what makes materialisation safe to re-run every minute and
    across restarts (section 5.5) - a restart never sends a second reminder.

    `state` is mutated ONLY by scheduler/state_machine.py (section 8).
    """

    __tablename__ = "dose_event"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_dose_event_idempotency_key"),
        Index("ix_dose_event_patient_scheduled", "patient_id", "scheduled_at"),
        Index("ix_dose_event_state_scheduled", "state", "scheduled_at"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    schedule_id: str = Field(foreign_key="schedule.id", index=True)

    #: Denormalised so the dashboard's 5-second poll is a single-table query.
    patient_id: str = Field(foreign_key="patient.id", index=True)

    idempotency_key: str = Field(index=True)

    #: When the dose is due, in UTC. Derived from the schedule's local HH:MM.
    scheduled_at: datetime = Field(index=True)

    state: str = Field(default="SCHEDULED", index=True, description="one of DOSE_STATES")

    sent_at: datetime | None = Field(default=None)
    followup_sent_at: datetime | None = Field(default=None)
    responded_at: datetime | None = Field(default=None)
    caretaker_alerted_at: datetime | None = Field(default=None)

    response_source: str | None = Field(default=None, description="one of RESPONSE_SOURCES")

    #: The patient's own words. Quoted verbatim in the doctor report (section 6).
    response_text: str | None = Field(default=None)
    reason: str | None = Field(default=None, description="stated reason for not taking")

    #: Supabase Storage key of the pre-generated Urdu voice note (Phase 5).
    #: Generated when the schedule is confirmed, never in the reminder path.
    voice_note_key: str | None = Field(default=None)

    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


# --------------------------------------------------------------------------
# 8. message_log
# --------------------------------------------------------------------------


class MessageLog(SQLModel, table=True):
    """Every inbound and outbound WhatsApp message.

    `wa_message_id` carries a UNIQUE index - this is the deduplication
    mechanism required by section 5.4. A rejected insert on a duplicate is
    correct behaviour, not a bug (section 17). The column is nullable because
    an outbound send that fails never receives an id from Meta, and Postgres
    permits many NULLs under a unique index.
    """

    __tablename__ = "message_log"
    __table_args__ = (
        UniqueConstraint("wa_message_id", name="uq_message_log_wa_message_id"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    wa_message_id: str | None = Field(default=None, index=True)

    direction: str = Field(index=True, description="one of MESSAGE_DIRECTIONS")
    kind: str = Field(default="text", description="one of MESSAGE_KINDS")

    patient_id: str | None = Field(default=None, foreign_key="patient.id", index=True)
    caretaker_id: str | None = Field(default=None, foreign_key="caretaker.id", index=True)
    dose_event_id: str | None = Field(default=None, foreign_key="dose_event.id", index=True)

    from_number: str | None = Field(default=None)
    to_number: str | None = Field(default=None)

    body: str | None = Field(default=None)

    #: Button payload, e.g. "TAKEN:<dose_id>" / "LATER:<dose_id>" (section 5.2).
    payload: str | None = Field(default=None)
    media_id: str | None = Field(default=None)
    template_name: str | None = Field(default=None)

    status: str | None = Field(default=None, description="sent / delivered / read / failed")
    error: str | None = Field(default=None)

    #: The untouched Meta payload, kept for debugging at 11pm (section 12).
    raw: dict | None = Field(default=None, sa_column=_json_column())

    created_at: datetime = Field(default_factory=utcnow, nullable=False)


# --------------------------------------------------------------------------
# 9. symptom_report
# --------------------------------------------------------------------------


class SymptomReport(SQLModel, table=True):
    """A symptom the patient mentioned.

    Recorded verbatim and never interpreted by the agent (section 5.8) - it is
    quoted as-is in the doctor report (section 6).
    """

    __tablename__ = "symptom_report"

    id: str = Field(default_factory=new_id, primary_key=True)
    patient_id: str = Field(foreign_key="patient.id", index=True)
    dose_event_id: str | None = Field(default=None, foreign_key="dose_event.id")

    text_verbatim: str
    language: str = Field(default="ur")
    severity: str = Field(default="routine", description="one of SYMPTOM_SEVERITIES")

    caretaker_alerted: bool = Field(default=False)
    reported_at: datetime = Field(default_factory=utcnow, nullable=False)


# --------------------------------------------------------------------------
# 10. prescription
# --------------------------------------------------------------------------


class Prescription(SQLModel, table=True):
    """A photographed prescription and its Qwen-VL extraction (Phase 7).

    `confirmation_state` starts "pending" and NOTHING is scheduled from it
    until a caretaker confirms - invariant 3.3, no exceptions for the demo.
    """

    __tablename__ = "prescription"

    id: str = Field(default_factory=new_id, primary_key=True)
    patient_id: str = Field(foreign_key="patient.id", index=True)
    uploaded_by: str | None = Field(default=None, foreign_key="caretaker.id")

    storage_key: str | None = Field(default=None)

    #: Raw Qwen-VL response, stored before any parsing so a bad extraction is
    #: debuggable rather than lost.
    raw_extraction: dict | None = Field(default=None, sa_column=_json_column())

    confirmation_state: str = Field(
        default="pending", description="one of PRESCRIPTION_STATES"
    )
    confirmed_by: str | None = Field(default=None, foreign_key="caretaker.id")
    confirmed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


# --------------------------------------------------------------------------
# 11. report
# --------------------------------------------------------------------------


class Report(SQLModel, table=True):
    """One generated PDF (section 8, and Phase 6 in section 14).

    `medicine_id` null means the report covers the whole patient rather than a
    single medicine's course.
    """

    __tablename__ = "report"

    id: str = Field(default_factory=new_id, primary_key=True)
    patient_id: str = Field(foreign_key="patient.id", index=True)
    medicine_id: str | None = Field(default=None, foreign_key="medicine.id", index=True)

    kind: str = Field(description="one of REPORT_KINDS")
    trigger: str = Field(default="on_demand", description="one of REPORT_TRIGGERS")

    period_start: date
    period_end: date
    storage_key: str

    generated_at: datetime = Field(default_factory=utcnow, nullable=False)


#: Import this wherever "every table" is needed (create_all, seeding, tests).
ALL_TABLES = [
    Family,
    Caretaker,
    Patient,
    MedicineReference,
    Medicine,
    Schedule,
    DoseEvent,
    MessageLog,
    SymptomReport,
    Prescription,
    Report,
]
