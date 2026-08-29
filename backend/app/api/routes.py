"""REST API for the Next.js dashboard.

Auth is Supabase: the browser signs in with email/password or Google, and
sends the resulting JWT as a Bearer token. This module verifies it against
Supabase's JWKS and maps the account to a `caretaker` row, creating one on
first sign-in.

A caretaker only ever sees their own family's data. Every patient-scoped
endpoint goes through `_owned_patient`, which is the single place that check
lives - so it cannot be forgotten on a new endpoint.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import jwt
from sqlalchemy.exc import IntegrityError
from fastapi import (APIRouter, BackgroundTasks, Depends, HTTPException,
                     Query, Request, Response)
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, col, func, select

from app.agent import knowledge
from app.config import settings
from app.db import get_session
from app.models import (Caretaker, DoseEvent, Family, Medicine,
                        MedicineReference, MessageLog, Patient, Report,
                        Schedule, SymptomReport)
from app.whatsapp.client import normalise_number

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["dashboard"])

_jwks_client: jwt.PyJWKClient | None = None


# ==========================================================================
# auth
# ==========================================================================


def _jwks() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        _jwks_client = jwt.PyJWKClient(url, cache_keys=True)
    return _jwks_client


def _decode(token: str) -> dict:
    """Verify a Supabase access token and return its claims.

    Supabase signs with asymmetric keys these days, so the public JWKS is
    enough - no shared secret has to live in our env.
    """
    try:
        key = _jwks().get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["ES256", "RS256"],
                          audience="authenticated",
                          options={"verify_exp": True})
    except Exception as exc:  # noqa: BLE001
        log.info("token rejected: %s", exc)
        raise HTTPException(401, "invalid or expired session") from exc


def _display_name(claims: dict) -> str | None:
    """The caretaker's name out of a Supabase JWT, whoever signed them in.

    Email sign-up puts the typed name in `full_name`. Google fills the same
    field, but also `name`, and other providers set only one or the other -
    so all of them are tried rather than assuming the shape of one. Falling
    through to None is fine: `_find_or_create` derives a name from the email.

    The caretaker's name is not decoration. It is spoken to the patient
    ("aap ke bete Usman ne...") and printed on the caretaker report, so an
    account that lands with a blank name is a message that reads oddly to a
    68-year-old.
    """
    meta = claims.get("user_metadata") or {}
    for key in ("full_name", "name", "preferred_username"):
        value = (meta.get(key) or "").strip()
        if value:
            return value
    return None


def _find_or_create(session: Session, *, auth_id: str, email: str | None,
                    name: str | None) -> Caretaker:
    """Map a Supabase account to a caretaker row, creating it on first login.

    A new caretaker gets their own family. Joining an existing family is a
    later concern; §4.10's "multiple caretakers per patient" is served by
    inviting someone into a family, not by guessing at sign-up.
    """
    row = session.exec(
        select(Caretaker).where(Caretaker.auth_user_id == auth_id)).first()
    if row:
        return row

    if email:
        row = session.exec(select(Caretaker).where(Caretaker.email == email)).first()
        if row:
            row.auth_user_id = auth_id
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    display = (name or (email or "").split("@")[0] or "Caretaker").strip()
    family = Family(name=f"{display}'s family")
    session.add(family)
    session.commit()
    session.refresh(family)

    row = Caretaker(family_id=family.id, name=display, email=email,
                    auth_user_id=auth_id, verified=True)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        # The dashboard opens several requests at once, so two of them can
        # reach this point together. The unique index on auth_user_id decides
        # which one wins; the loser adopts the winner's row and bins the
        # family it optimistically created. Without this, one sign-in produced
        # four caretakers and four families.
        session.rollback()
        session.delete(session.get(Family, family.id))
        session.commit()
        existing = session.exec(
            select(Caretaker).where(Caretaker.auth_user_id == auth_id)).first()
        if existing is None:
            raise
        log.info("lost the create race for %s - using the existing row", auth_id)
        return existing

    session.refresh(row)
    log.info("new caretaker %s (%s) with family %s", row.id, email, family.id)
    return row


def current_caretaker(request: Request,
                      session: Session = Depends(get_session)) -> Caretaker:
    """The signed-in caretaker. 401 if there is no valid session."""
    header = request.headers.get("authorization", "")

    if header.lower().startswith("bearer "):
        claims = _decode(header.split(" ", 1)[1])
        return _find_or_create(
            session,
            auth_id=claims["sub"],
            email=claims.get("email"),
            name=_display_name(claims),
        )

    # Dev bypass (§4.1). Off unless explicitly enabled, and it says so loudly.
    if settings.dev_auth_bypass:
        log.warning("DEV AUTH BYPASS in use - never enable this in production")
        return _find_or_create(session, auth_id="dev-bypass-user",
                               email="dev@mednuskha.local", name="Dev Caretaker")

    raise HTTPException(401, "sign in required")


def _owned_patient(patient_id: str, caretaker: Caretaker,
                   session: Session) -> Patient:
    """Fetch a patient, or 404 if they are not in the caretaker's family.

    404 rather than 403 on purpose: a caretaker should not be able to learn
    that a given patient id exists at all.
    """
    patient = session.get(Patient, patient_id)
    if patient is None or patient.family_id != caretaker.family_id:
        raise HTTPException(404, "patient not found")
    return patient


# ==========================================================================
# request bodies
# ==========================================================================


class ProfileIn(BaseModel):
    name: str | None = None
    phone: str | None = None
    relation: str | None = None
    language: str | None = None


class PatientIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    whatsapp_number: str
    language: str = "ur"
    relation: str = Field(default="beta", max_length=40)

    @field_validator("whatsapp_number")
    @classmethod
    def _digits(cls, v: str) -> str:
        cleaned = normalise_number(v)
        if len(cleaned) < 10:
            raise ValueError("that does not look like a WhatsApp number")
        return cleaned

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str) -> str:
        return v if v in ("ur", "en") else "ur"


class LookupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ScheduleIn(BaseModel):
    """Change the times or the length of a course that is already running."""

    dose_times: list[str] = Field(min_length=1, max_length=6)
    duration_days: int = Field(ge=1, le=365)
    strength: str | None = None

    @field_validator("dose_times")
    @classmethod
    def _times(cls, v: list[str]) -> list[str]:
        out = []
        for raw in v:
            try:
                hh, mm = raw.strip().split(":")
                h, m = int(hh), int(mm)
                assert 0 <= h < 24 and 0 <= m < 60
            except Exception as exc:
                raise ValueError(f"bad dose time {raw!r}, expected HH:MM") from exc
            out.append(f"{h:02d}:{m:02d}")
        return sorted(set(out))


class MedicineIn(BaseModel):
    patient_id: str
    name: str = Field(min_length=1, max_length=120)
    strength: str | None = None
    form: str | None = None

    #: Local "HH:MM" times, e.g. ["08:00", "20:00"].
    dose_times: list[str] = Field(min_length=1, max_length=6)
    duration_days: int = Field(ge=1, le=365)

    # The caretaker-reviewed draft. Saved to medicine_reference as CONFIRMED,
    # which is the only way a row ever becomes confirmed (invariant 9).
    purpose_ur: str | None = None
    purpose_en: str | None = None
    food_rule: str | None = None
    common_timing: str | None = None
    edited: bool = False

    @field_validator("dose_times")
    @classmethod
    def _times(cls, v: list[str]) -> list[str]:
        out = []
        for raw in v:
            try:
                hh, mm = raw.strip().split(":")
                h, m = int(hh), int(mm)
                assert 0 <= h < 24 and 0 <= m < 60
            except Exception as exc:
                raise ValueError(f"bad dose time {raw!r}, expected HH:MM") from exc
            out.append(f"{h:02d}:{m:02d}")
        return sorted(set(out))


# ==========================================================================
# helpers
# ==========================================================================


def _local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(settings.tz)


def _today_bounds() -> tuple[datetime, datetime]:
    now_local = datetime.now(settings.tz)
    start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


TAKEN_STATES = ("TAKEN", "TAKEN_LATE")
DECIDED_STATES = ("TAKEN", "TAKEN_LATE", "MISSED", "SKIPPED")


def _adherence(session: Session, patient_id: str, *, days: int = 14,
               medicine_id: str | None = None) -> dict:
    """Percentage of decided doses that were actually taken.

    Doses still awaiting an answer are excluded - counting a dose that is due
    in four hours as "missed" would make every patient look terrible in the
    morning.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = (select(DoseEvent.state, func.count())
             .where(DoseEvent.patient_id == patient_id)
             .where(DoseEvent.scheduled_at >= since)
             .group_by(DoseEvent.state))
    if medicine_id:
        query = (query.join(Schedule, Schedule.id == DoseEvent.schedule_id)
                 .where(Schedule.medicine_id == medicine_id))

    counts = {state: n for state, n in session.exec(query).all()}
    taken = sum(counts.get(s, 0) for s in TAKEN_STATES)
    decided = sum(counts.get(s, 0) for s in DECIDED_STATES)
    return {
        "taken": taken,
        "on_time": counts.get("TAKEN", 0),
        "late": counts.get("TAKEN_LATE", 0),
        "missed": counts.get("MISSED", 0),
        "skipped": counts.get("SKIPPED", 0),
        "pending": sum(counts.get(s, 0)
                       for s in ("SCHEDULED", "SENT", "AWAITING_REPLY",
                                 "REMINDED_AGAIN")),
        "decided": decided,
        "percent": round(taken / decided * 100) if decided else None,
        "days": days,
    }


def _dose_json(dose: DoseEvent, medicine: Medicine) -> dict:
    label = f"{medicine.name} {medicine.strength}".strip() if medicine.strength \
        else medicine.name
    return {
        "id": dose.id,
        "medicine_id": medicine.id,
        "medicine": label,
        "state": dose.state,
        "scheduled_at": _local(dose.scheduled_at).isoformat(),
        "time": _local(dose.scheduled_at).strftime("%H:%M"),
        "sent_at": _local(dose.sent_at).isoformat() if dose.sent_at else None,
        "responded_at": _local(dose.responded_at).isoformat() if dose.responded_at else None,
        "response_source": dose.response_source,
        "response_text": dose.response_text,
        "reason": dose.reason,
        "caretaker_alerted": dose.caretaker_alerted_at is not None,
    }


# ==========================================================================
# me
# ==========================================================================


@router.get("/me")
def get_me(caretaker: Caretaker = Depends(current_caretaker),
           session: Session = Depends(get_session)) -> dict:
    family = session.get(Family, caretaker.family_id)
    patients = session.exec(
        select(Patient).where(Patient.family_id == caretaker.family_id)).all()
    return {
        "id": caretaker.id,
        "name": caretaker.name,
        "email": caretaker.email,
        "phone": caretaker.phone,
        "relation": caretaker.relation,
        "language": caretaker.language,
        "family": {"id": family.id if family else None,
                   "name": family.name if family else None},
        "patient_count": len(patients),
        "needs_phone": not caretaker.phone,
    }


@router.patch("/me")
def update_me(body: ProfileIn,
              caretaker: Caretaker = Depends(current_caretaker),
              session: Session = Depends(get_session)) -> dict:
    if body.name:
        caretaker.name = body.name.strip()
    if body.relation:
        caretaker.relation = body.relation.strip()
    if body.language in ("ur", "en"):
        caretaker.language = body.language
    if body.phone is not None:
        cleaned = normalise_number(body.phone)
        if cleaned and len(cleaned) < 10:
            raise HTTPException(422, "that does not look like a WhatsApp number")
        clash = session.exec(
            select(Caretaker).where(Caretaker.phone == cleaned)
            .where(Caretaker.id != caretaker.id)).first() if cleaned else None
        if clash:
            raise HTTPException(409, "that number is already registered")
        caretaker.phone = cleaned or None

    session.add(caretaker)
    session.commit()
    session.refresh(caretaker)
    return get_me(caretaker, session)


# ==========================================================================
# patients
# ==========================================================================


@router.get("/patients")
def list_patients(caretaker: Caretaker = Depends(current_caretaker),
                  session: Session = Depends(get_session)) -> list[dict]:
    """Family overview: every patient with today's adherence at a glance."""
    start, end = _today_bounds()
    out = []
    for patient in session.exec(
            select(Patient).where(Patient.family_id == caretaker.family_id)
            .order_by(Patient.created_at)).all():

        today = session.exec(
            select(DoseEvent)
            .where(DoseEvent.patient_id == patient.id)
            .where(DoseEvent.scheduled_at >= start)
            .where(DoseEvent.scheduled_at < end)).all()

        medicines = session.exec(
            select(Medicine).where(Medicine.patient_id == patient.id)
            .where(Medicine.active == True)).all()      # noqa: E712

        out.append({
            "id": patient.id,
            "name": patient.name,
            "whatsapp_number": patient.whatsapp_number,
            "language": patient.language,
            "opted_in": patient.opted_in,
            "stopped": patient.stopped,
            "medicine_count": len(medicines),
            "today": {
                "total": len(today),
                "taken": sum(1 for d in today if d.state in TAKEN_STATES),
                "missed": sum(1 for d in today if d.state == "MISSED"),
                "pending": sum(1 for d in today if d.state not in DECIDED_STATES),
            },
            "adherence": _adherence(session, patient.id),
        })
    return out


@router.post("/patients", status_code=201)
def create_patient(body: PatientIn,
                   caretaker: Caretaker = Depends(current_caretaker),
                   session: Session = Depends(get_session)) -> dict:
    existing = session.exec(
        select(Patient).where(Patient.whatsapp_number == body.whatsapp_number)).first()
    if existing:
        raise HTTPException(409, "a patient with that WhatsApp number already exists")

    patient = Patient(family_id=caretaker.family_id, name=body.name.strip(),
                      whatsapp_number=body.whatsapp_number, language=body.language,
                      # Reminders start immediately. The opt-in message is sent
                      # separately and flips this to a confirmed true.
                      opted_in=True, opted_in_at=datetime.now(timezone.utc))
    session.add(patient)

    # §8: the caretaker's relation to the patient is set when they link.
    if body.relation and caretaker.relation in (None, "", "caregiver"):
        caretaker.relation = body.relation.strip()
        session.add(caretaker)

    session.commit()
    session.refresh(patient)
    log.info("caretaker %s added patient %s", caretaker.id, patient.id)
    return {"id": patient.id, "name": patient.name,
            "whatsapp_number": patient.whatsapp_number}


@router.get("/patients/{patient_id}")
def get_patient(patient_id: str,
                caretaker: Caretaker = Depends(current_caretaker),
                session: Session = Depends(get_session)) -> dict:
    patient = _owned_patient(patient_id, caretaker, session)
    today = date.today()

    medicines = []
    for medicine in session.exec(
            select(Medicine).where(Medicine.patient_id == patient.id)
            .order_by(Medicine.created_at)).all():
        schedule = session.exec(
            select(Schedule).where(Schedule.medicine_id == medicine.id)).first()
        reference = session.get(MedicineReference, medicine.reference_id) \
            if medicine.reference_id else None

        remaining = None
        if schedule:
            remaining = max(0, (schedule.end_date - today).days + 1)

        medicines.append({
            "id": medicine.id,
            "name": medicine.name,
            "strength": medicine.strength,
            "form": medicine.form,
            "active": medicine.active,
            "schedule": {
                "dose_times": schedule.dose_times if schedule else [],
                "duration_days": schedule.duration_days if schedule else None,
                "start_date": schedule.start_date.isoformat() if schedule else None,
                "end_date": schedule.end_date.isoformat() if schedule else None,
                "days_remaining": remaining,
                "finished": bool(schedule and schedule.end_date < today),
            } if schedule else None,
            "info": {
                "purpose_ur": reference.purpose_ur if reference else None,
                "purpose_en": reference.purpose_en if reference else None,
                "food_rule": reference.food_rule if reference else None,
                "confirmed": bool(reference and reference.confirmed),
            } if reference else None,
            "adherence": _adherence(session, patient.id, medicine_id=medicine.id),
        })

    return {
        "id": patient.id,
        "name": patient.name,
        "whatsapp_number": patient.whatsapp_number,
        "language": patient.language,
        "opted_in": patient.opted_in,
        "stopped": patient.stopped,
        "medicines": medicines,
        "adherence": _adherence(session, patient.id),
    }


@router.get("/patients/{patient_id}/today")
def today_doses(patient_id: str,
                caretaker: Caretaker = Depends(current_caretaker),
                session: Session = Depends(get_session)) -> dict:
    """Today's doses. Polled every 5 seconds while the page is open."""
    patient = _owned_patient(patient_id, caretaker, session)
    start, end = _today_bounds()

    rows = session.exec(
        select(DoseEvent, Medicine)
        .join(Schedule, Schedule.id == DoseEvent.schedule_id)
        .join(Medicine, Medicine.id == Schedule.medicine_id)
        .where(DoseEvent.patient_id == patient.id)
        .where(DoseEvent.scheduled_at >= start)
        .where(DoseEvent.scheduled_at < end)
        .order_by(DoseEvent.scheduled_at)).all()

    doses = [_dose_json(d, m) for d, m in rows]
    return {
        "patient_id": patient.id,
        "date": datetime.now(settings.tz).date().isoformat(),
        "server_time": datetime.now(settings.tz).strftime("%H:%M"),
        "doses": doses,
        "summary": {
            "total": len(doses),
            "taken": sum(1 for d in doses if d["state"] in TAKEN_STATES),
            "missed": sum(1 for d in doses if d["state"] == "MISSED"),
            "pending": sum(1 for d in doses if d["state"] not in DECIDED_STATES),
        },
    }


@router.get("/patients/{patient_id}/history")
def dose_history(patient_id: str, days: int = Query(14, ge=1, le=90),
                 caretaker: Caretaker = Depends(current_caretaker),
                 session: Session = Depends(get_session)) -> dict:
    """Every dose over the last `days`, for the adherence chart.

    Deliberately the same `_dose_json` shape as `/today` - the chart and the
    day view read one format, so a column in the chart and a row in today's
    list can never disagree about what happened.
    """
    patient = _owned_patient(patient_id, caretaker, session)
    _, end = _today_bounds()
    start = end - timedelta(days=days)

    rows = session.exec(
        select(DoseEvent, Medicine)
        .join(Schedule, Schedule.id == DoseEvent.schedule_id)
        .join(Medicine, Medicine.id == Schedule.medicine_id)
        .where(DoseEvent.patient_id == patient.id)
        .where(DoseEvent.scheduled_at >= start)
        .where(DoseEvent.scheduled_at < end)
        .order_by(DoseEvent.scheduled_at)).all()

    return {
        "patient_id": patient.id,
        "days": days,
        "doses": [_dose_json(d, m) for d, m in rows],
    }


@router.get("/patients/{patient_id}/events")
def event_log(patient_id: str, limit: int = Query(50, ge=1, le=200),
              caretaker: Caretaker = Depends(current_caretaker),
              session: Session = Depends(get_session)) -> list[dict]:
    """Everything that happened, newest first - messages and symptoms."""
    patient = _owned_patient(patient_id, caretaker, session)

    events: list[dict] = []
    for row in session.exec(
            select(MessageLog).where(MessageLog.patient_id == patient.id)
            .order_by(col(MessageLog.created_at).desc()).limit(limit)).all():
        events.append({
            "kind": "message",
            "at": _local(row.created_at).isoformat(),
            "direction": row.direction,
            "type": row.kind,
            "body": row.body,
            "template": row.template_name,
            "status": row.status,
            "error": row.error,
        })

    for row in session.exec(
            select(SymptomReport).where(SymptomReport.patient_id == patient.id)
            .order_by(col(SymptomReport.reported_at).desc()).limit(20)).all():
        events.append({
            "kind": "symptom",
            "at": _local(row.reported_at).isoformat(),
            "body": row.text_verbatim,
            "severity": row.severity,
        })

    events.sort(key=lambda e: e["at"], reverse=True)
    return events[:limit]


# ==========================================================================
# medicines
# ==========================================================================


@router.post("/medicines/lookup")
async def lookup_medicine(body: LookupIn,
                          caretaker: Caretaker = Depends(current_caretaker)) -> dict:
    """Draft the medicine information for the caretaker to review.

    Reuses an existing row when there is one, so the same medicine is not
    looked up twice. **The result is a DRAFT either way** - even an already
    confirmed row is shown for review, because §14 Phase 4 requires the
    caretaker to see it before it applies to *their* patient.
    """
    existing = knowledge.get_any(body.name)
    if existing is not None:
        return {"source": "existing", "already_confirmed": existing.confirmed,
                **existing.as_dict()}

    draft = await knowledge.fetch_draft(body.name)
    recognised = any([draft.purpose_ur, draft.purpose_en, draft.food_rule])
    return {"source": "ai_fetched", "already_confirmed": False,
            "recognised": recognised, **draft.as_dict()}


@router.post("/medicines", status_code=201)
async def create_medicine(body: MedicineIn,
                          background: BackgroundTasks,
                          caretaker: Caretaker = Depends(current_caretaker),
                          session: Session = Depends(get_session)) -> dict:
    """Confirm and add. One transaction: reference row, medicine, schedule.

    Reaching this endpoint IS the caretaker's confirmation - it is the only
    thing that ever sets `confirmed = true` (invariant 9).
    """
    patient = _owned_patient(body.patient_id, caretaker, session)

    reference_id = await knowledge.save_confirmed(
        body.name,
        knowledge.MedicineInfoDraft(
            canonical_name=body.name,
            purpose_ur=body.purpose_ur, purpose_en=body.purpose_en,
            food_rule=body.food_rule, common_timing=body.common_timing,
            source="caretaker_edited" if body.edited else "ai_fetched",
        ),
        caretaker_id=caretaker.id,
    )

    medicine = Medicine(patient_id=patient.id, reference_id=reference_id,
                        name=body.name.strip(), strength=(body.strength or "").strip() or None,
                        form=(body.form or "").strip() or None)
    session.add(medicine)
    session.commit()
    session.refresh(medicine)

    start = date.today()
    # end_date is INCLUSIVE - the last day a dose is due (SCHEMA.md).
    schedule = Schedule(medicine_id=medicine.id, dose_times=body.dose_times,
                        duration_days=body.duration_days, start_date=start,
                        end_date=start + timedelta(days=body.duration_days - 1))
    session.add(schedule)
    session.commit()
    session.refresh(schedule)

    log.info("caretaker %s added %s for patient %s (%d days, %s)",
             caretaker.id, medicine.name, patient.id,
             body.duration_days, body.dose_times)

    # Materialise straight away so the dashboard shows today's doses without
    # waiting up to a minute for the next tick.
    try:
        from app.scheduler.ticker import materialise_doses
        materialise_doses()
    except Exception as exc:  # noqa: BLE001 - the ticker will catch up
        log.warning("immediate materialisation failed: %s", exc)

    # Phase 5. Confirming the schedule is the moment the wording is final, so
    # it is the moment to synthesise - never in the reminder path (3.4).
    _pregenerate_voice(background, medicine.id)

    return {
        "id": medicine.id,
        "name": medicine.name,
        "schedule": {
            "dose_times": schedule.dose_times,
            "duration_days": schedule.duration_days,
            "start_date": schedule.start_date.isoformat(),
            "end_date": schedule.end_date.isoformat(),
        },
    }


@router.patch("/medicines/{medicine_id}")
def update_schedule(medicine_id: str, body: ScheduleIn,
                    background: BackgroundTasks,
                    caretaker: Caretaker = Depends(current_caretaker),
                    session: Session = Depends(get_session)) -> dict:
    """Change the dose times or the length of a course already running.

    Doses that have already been sent or answered are left alone - they are
    history, and the reports are made of them. Only future doses that no
    longer match the new times are removed, and the new ones are materialised
    immediately so the dashboard reflects the change straight away.
    """
    medicine = session.get(Medicine, medicine_id)
    if medicine is None:
        raise HTTPException(404, "medicine not found")
    _owned_patient(medicine.patient_id, caretaker, session)

    schedule = session.exec(
        select(Schedule).where(Schedule.medicine_id == medicine.id)).first()
    if schedule is None:
        raise HTTPException(404, "this medicine has no schedule")

    if body.strength is not None:
        medicine.strength = body.strength.strip() or None
        session.add(medicine)

    schedule.dose_times = body.dose_times
    schedule.duration_days = body.duration_days
    # end_date stays INCLUSIVE - the last day a dose is due (SCHEMA.md).
    schedule.end_date = schedule.start_date + timedelta(days=body.duration_days - 1)
    schedule.active = True
    medicine.active = True
    session.add(schedule)
    session.add(medicine)
    session.commit()

    removed = _drop_stale_doses(session, schedule)

    try:
        from app.scheduler.ticker import materialise_doses
        created = materialise_doses()
    except Exception as exc:  # noqa: BLE001 - the ticker will catch up
        log.warning("re-materialisation after edit failed: %s", exc)
        created = 0

    # New times mean new sentences ("8 baj gaye" -> "9 baj gaye"), and new
    # doses with no audio attached yet.
    _pregenerate_voice(background, medicine.id)

    log.info("caretaker %s changed %s to %s for %d days (%d dropped, %d created)",
             caretaker.id, medicine.name, body.dose_times, body.duration_days,
             removed, created)

    return {
        "id": medicine.id,
        "dose_times": schedule.dose_times,
        "duration_days": schedule.duration_days,
        "end_date": schedule.end_date.isoformat(),
        "doses_removed": removed,
        "doses_created": created,
    }


def _pregenerate_voice(background: BackgroundTasks, medicine_id: str) -> None:
    """Queue the Urdu voice notes for a medicine, after the response is sent.

    A background task, not an await: synthesis is a network round trip per
    unique dose time, and a caretaker pressing Confirm should not sit and
    watch a spinner for it. If it fails the medicine is still added and every
    reminder still goes out as text - `pregenerate_for_medicine` swallows its
    own failures for exactly that reason.
    """
    if not settings.voice_notes_enabled:
        return
    from app.voice.tts import pregenerate_for_medicine

    background.add_task(pregenerate_for_medicine, medicine_id)


#: A dose due within this window is left alone - the ticker may already be
#: mid-send, and yanking the row out from under it is worse than one extra
#: reminder.
_TICKER_RACE_WINDOW = timedelta(seconds=90)


def _drop_stale_doses(session: Session, schedule: Schedule) -> int:
    """Remove never-sent doses that no longer match the schedule.

    Only SCHEDULED doses are touched. Anything SENT, answered or missed is
    history and is left exactly as it is - rewriting what actually happened
    would corrupt the reports.

    Past-due SCHEDULED doses are removed too, not just future ones. A dose at
    a time the caretaker has just deleted was never sent to anybody, so
    leaving it would have the ticker report a MISSED dose for a time that no
    longer exists on the schedule.
    """
    now = datetime.now(timezone.utc)
    wanted = set(schedule.dose_times)
    removed = 0

    for dose in session.exec(
            select(DoseEvent)
            .where(DoseEvent.schedule_id == schedule.id)
            .where(DoseEvent.state == "SCHEDULED")).all():
        due = dose.scheduled_at
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        if abs(due - now) <= _TICKER_RACE_WINDOW:
            continue                       # the ticker may be mid-send

        local = due.astimezone(settings.tz)
        if local.strftime("%H:%M") in wanted and local.date() <= schedule.end_date:
            continue                       # still valid

        for row in session.exec(
                select(MessageLog).where(MessageLog.dose_event_id == dose.id)).all():
            row.dose_event_id = None       # keep the message, drop the link
            session.add(row)
        session.delete(dose)
        removed += 1

    session.commit()
    return removed


@router.delete("/medicines/{medicine_id}")
def remove_medicine(medicine_id: str, permanent: bool = Query(False),
                    caretaker: Caretaker = Depends(current_caretaker),
                    session: Session = Depends(get_session)) -> dict:
    """Stop a medicine, or delete it outright.

    Stopping is the default and the safer one: reminders end but the history
    stays, which is what the reports are made of. `permanent=true` is for a
    mistake - a medicine added with the wrong name, or added twice - and it
    takes the dose history with it. Messages that were genuinely sent are kept
    and simply unlinked, because those really did reach the patient.
    """
    medicine = session.get(Medicine, medicine_id)
    if medicine is None:
        raise HTTPException(404, "medicine not found")
    _owned_patient(medicine.patient_id, caretaker, session)

    if not permanent:
        medicine.active = False
        session.add(medicine)
        for schedule in session.exec(
                select(Schedule).where(Schedule.medicine_id == medicine.id)).all():
            schedule.active = False
            session.add(schedule)
        session.commit()
        log.info("caretaker %s stopped medicine %s", caretaker.id, medicine_id)
        return {"stopped": True, "deleted": False}

    name = medicine.name
    schedules = session.exec(
        select(Schedule).where(Schedule.medicine_id == medicine.id)).all()

    doses = []
    for schedule in schedules:
        doses.extend(session.exec(
            select(DoseEvent).where(DoseEvent.schedule_id == schedule.id)).all())

    # Unlink first, in strict foreign-key order, or Postgres refuses.
    for dose in doses:
        for row in session.exec(
                select(MessageLog).where(MessageLog.dose_event_id == dose.id)).all():
            row.dose_event_id = None
            session.add(row)
        for row in session.exec(
                select(SymptomReport).where(
                    SymptomReport.dose_event_id == dose.id)).all():
            row.dose_event_id = None
            session.add(row)
    session.commit()

    for dose in doses:
        session.delete(dose)
    session.commit()

    for schedule in schedules:
        session.delete(schedule)
    session.commit()

    for row in session.exec(
            select(Report).where(Report.medicine_id == medicine.id)).all():
        session.delete(row)
    session.commit()

    session.delete(medicine)
    session.commit()

    log.warning("caretaker %s PERMANENTLY deleted medicine %s (%s) and %d doses",
                caretaker.id, medicine_id, name, len(doses))
    return {"stopped": True, "deleted": True, "doses_removed": len(doses)}


# ==========================================================================
# patient messaging
# ==========================================================================


@router.post("/patients/{patient_id}/optin")
async def send_optin(patient_id: str,
                     caretaker: Caretaker = Depends(current_caretaker),
                     session: Session = Depends(get_session)) -> dict:
    """Send the opt-in message so the patient knows what is about to arrive."""
    patient = _owned_patient(patient_id, caretaker, session)
    from app.whatsapp import client as wa

    message_id = await wa.send_template(
        to=patient.whatsapp_number, template="patient_optin",
        lang=patient.language, body_vars=[patient.name, caretaker.name])
    return {"sent": True, "message_id": message_id}


@router.post("/patients/{patient_id}/resume")
def resume_patient(patient_id: str,
                   caretaker: Caretaker = Depends(current_caretaker),
                   session: Session = Depends(get_session)) -> dict:
    """Start reminders again for a patient who had stopped.

    A patient can halt everything by replying STOP, and the agent errs towards
    honouring that. But a phrase can be misread - "nahi mana krdo" was, on a
    real phone - and without this the caretaker has no way back and every
    future reminder is silently dead.
    """
    patient = _owned_patient(patient_id, caretaker, session)
    patient.stopped = False
    patient.opted_in = True
    if patient.opted_in_at is None:
        patient.opted_in_at = datetime.now(timezone.utc)
    session.add(patient)
    session.commit()

    try:
        from app.scheduler.ticker import materialise_doses
        created = materialise_doses()
    except Exception as exc:  # noqa: BLE001 - the ticker will catch up
        log.warning("materialisation after resume failed: %s", exc)
        created = 0

    log.info("caretaker %s resumed reminders for patient %s (%d doses)",
             caretaker.id, patient_id, created)
    return {"resumed": True, "doses_created": created}


@router.get("/whatsapp/status")
async def whatsapp_status(caretaker: Caretaker = Depends(current_caretaker)) -> dict:
    """Whether messages can actually go out right now."""
    from app.whatsapp.client import bridge_status

    return await bridge_status()


# ==========================================================================
# reports (Phase 6)
# ==========================================================================


@router.get("/patients/{patient_id}/report.pdf")
def patient_report(patient_id: str,
                   kind: str = Query("doctor", pattern="^(doctor|caretaker)$"),
                   medicine_id: str | None = Query(None),
                   caretaker: Caretaker = Depends(current_caretaker),
                   session: Session = Depends(get_session)) -> Response:
    """Generate either report for one course, right now (`trigger=on_demand`).

    The PDF is streamed back rather than redirected to, so the button works
    whether or not Supabase Storage is configured - archiving is best-effort.
    """
    from app.reports import data as report_data
    from app.reports import service

    patient = _owned_patient(patient_id, caretaker, session)

    if medicine_id is None:
        medicine_id = report_data.latest_medicine_id(patient_id)
        if medicine_id is None:
            raise HTTPException(404, "this patient has no medicine to report on")
    else:
        medicine = session.get(Medicine, medicine_id)
        if medicine is None or medicine.patient_id != patient_id:
            raise HTTPException(404, "medicine not found")

    try:
        row, blob = service.generate(
            kind, patient_id, medicine_id, trigger="on_demand",
            lang=caretaker.language or "en")
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc

    log.info("caretaker %s downloaded the %s report for patient %s",
             caretaker.id, kind, patient_id)
    return Response(
        content=blob,
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'inline; filename="{_report_filename(patient.name, kind, row)}"'},
    )


@router.get("/reports/{report_id}.pdf")
def shared_report(report_id: str, t: str = Query("", max_length=64)) -> Response:
    """A report opened from the WhatsApp link. Deliberately unauthenticated.

    A caretaker taps this on their phone, where there is no Bearer token, so
    the guard is the HMAC token in `t` instead. The `report` table was frozen
    at the end of Phase 0 with nowhere to store a token, so it is derived from
    the report id under WEBHOOK_SECRET rather than stored - see
    reports/storage.py.
    """
    from app.reports import service, storage

    if not storage.token_ok(report_id, t):
        # 404, not 403: a wrong token must not confirm the report exists.
        raise HTTPException(404, "report not found")

    found = service.fetch(report_id)
    if found is None:
        raise HTTPException(404, "report not found")

    row, blob = found
    return Response(
        content=blob,
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'inline; filename="mednuskha-{row.kind}-{row.period_end}.pdf"',
                 # A share link is per-report and immutable once generated.
                 "Cache-Control": "private, max-age=3600"},
    )


def _report_filename(patient_name: str, kind: str, row: Report) -> str:
    safe = "".join(c for c in patient_name if c.isalnum() or c in " -_").strip()
    safe = safe.replace(" ", "-").lower() or "patient"
    return f"{safe}-{kind}-{row.period_end}.pdf"
