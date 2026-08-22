"""Meta webhook endpoints: GET verify, POST receive.

Invariant 3: POST returns HTTP 200 within 2 seconds, BEFORE any processing.
FastAPI's BackgroundTasks run after the response has been sent, so the handler
parses nothing and touches no database - it hands the raw body over and
returns.

Invariant 4: every inbound message is deduplicated on Meta's wa_message_id via
the UNIQUE index on message_log. Meta retries aggressively when a webhook is
slow, so duplicates are normal traffic, not an error (section 17).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db import session_scope
from app.models import Caretaker, DoseEvent, MessageLog, Patient
from app.whatsapp.client import normalise_number
from app.whatsapp.parser import (
    InboundMessage,
    StatusUpdate,
    parse_statuses,
    parse_webhook,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["whatsapp"])


# --------------------------------------------------------------------------
# GET /webhook - Meta's subscription handshake
# --------------------------------------------------------------------------


@router.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    """Echo hub.challenge back as PLAIN TEXT, not JSON (section 10).

    Returning JSON here is the classic reason "Verify and save" fails in the
    Meta dashboard even though the endpoint is reachable.
    """
    if not settings.whatsapp_verify_token:
        log.error("webhook verify attempted but WHATSAPP_VERIFY_TOKEN is not set")
        return PlainTextResponse("verify token not configured", status_code=500)

    if hub_mode == "subscribe" and hub_token == settings.whatsapp_verify_token:
        log.info("webhook verified by Meta")
        return PlainTextResponse(hub_challenge or "")

    log.warning("webhook verification rejected (mode=%s, token matched=%s)",
                hub_mode, hub_token == settings.whatsapp_verify_token)
    return PlainTextResponse("forbidden", status_code=403)


# --------------------------------------------------------------------------
# POST /webhook - inbound messages and delivery receipts
# --------------------------------------------------------------------------


@router.post("/webhook")
async def receive_webhook(request: Request, background: BackgroundTasks) -> Response:
    """Accept an inbound webhook, enqueue it, return 200 immediately.

    Nothing is parsed here on purpose. Meta gives us a couple of seconds and
    retries the whole batch if we miss it.
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - a malformed body is still a 200
        log.warning("webhook body was not JSON; acknowledging anyway")
        return Response(status_code=200)

    background.add_task(process_webhook, body)
    return Response(status_code=200)


# --------------------------------------------------------------------------
# background processing
# --------------------------------------------------------------------------


def process_webhook(body: dict) -> None:
    """Parse and persist one webhook body. Runs after the 200 has been sent."""
    try:
        messages = parse_webhook(body)
        statuses = parse_statuses(body)
    except Exception as exc:  # noqa: BLE001 - never crash the background task
        log.exception("webhook parse failed: %s", exc)
        return

    for status in statuses:
        try:
            _apply_status(status)
        except Exception as exc:  # noqa: BLE001
            log.warning("status update failed for %s: %s", status.wa_message_id, exc)

    for msg in messages:
        try:
            _process_message(msg, body)
        except Exception as exc:  # noqa: BLE001 - one bad message must not
            log.exception("inbound %s failed: %s", msg.wa_message_id, exc)


def _process_message(msg: InboundMessage, raw_body: dict) -> None:
    """Persist one inbound message, deduplicating on wa_message_id."""
    number = normalise_number(msg.from_number)

    with session_scope() as session:
        patient = session.query(Patient).filter(
            Patient.whatsapp_number == number).first()
        caretaker = None
        if patient is None:
            caretaker = session.query(Caretaker).filter(
                Caretaker.phone == number).first()

        row = MessageLog(
            wa_message_id=msg.wa_message_id,
            direction="in",
            kind=msg.kind,
            patient_id=patient.id if patient else None,
            caretaker_id=caretaker.id if caretaker else None,
            dose_event_id=_dose_id_from(msg, session),
            from_number=number,
            to_number=settings.whatsapp_phone_number_id or None,
            body=msg.text,
            payload=msg.payload,
            media_id=msg.media_id,
            status="received",
            raw=raw_body,
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            # Two very different things land here, and treating them alike
            # loses messages. A duplicate is Meta redelivering something we
            # already handled - correct behaviour, not a bug (section 17).
            # Anything else is a real failure and must be shouted about.
            already = session.query(MessageLog).filter(
                MessageLog.wa_message_id == msg.wa_message_id).first()
            if already is not None:
                log.info("duplicate inbound %s ignored", msg.wa_message_id)
                return
            log.error("could not persist inbound %s: %s", msg.wa_message_id, exc)
            return

    who = patient.name if patient else (caretaker.name if caretaker else "unknown")
    log.info("inbound %s from %s (%s): kind=%s payload=%s text=%r",
             msg.wa_message_id, number, who, msg.kind, msg.payload, msg.text)

    if patient is None and caretaker is None:
        log.warning("inbound from an unregistered number %s - ignoring", number)
        return

    _route(msg, patient, caretaker)


def _dose_id_from(msg: InboundMessage, session) -> str | None:
    """Pull the dose id out of a button payload (invariant 2).

    Only ever taken from the payload. Which dose a reply refers to is never
    inferred from timing.

    The id is checked against dose_event before it is used, because
    message_log.dose_event_id is a foreign key: a payload naming a dose that
    no longer exists would otherwise fail the whole insert and lose the
    message. The raw payload is still stored either way, so nothing is lost.
    """
    if not msg.payload:
        return None
    from app.whatsapp.client import DOSE_PAYLOAD_RE

    match = DOSE_PAYLOAD_RE.match(msg.payload)
    if not match:
        return None

    dose_id = match.group("dose_id")
    if session.get(DoseEvent, dose_id) is None:
        log.warning("inbound %s names dose %s, which does not exist - "
                    "storing the payload without the link",
                    msg.wa_message_id, dose_id)
        return None
    return dose_id


def _apply_status(status: StatusUpdate) -> None:
    """Record a delivery receipt against the outbound row it belongs to."""
    if not status.wa_message_id:
        return
    with session_scope() as session:
        row = session.query(MessageLog).filter(
            MessageLog.wa_message_id == status.wa_message_id).first()
        if row is None:
            return
        row.status = status.status
        if status.error:
            row.error = status.error
        session.add(row)
        session.commit()

    if status.status == "failed":
        log.error("delivery FAILED for %s: %s", status.wa_message_id, status.error)


def _route(msg: InboundMessage, patient: Patient | None,
           caretaker: Caretaker | None) -> None:
    """Hand a persisted message on to whoever owns it.

    Phase 1 is transport only: the message is stored and logged. Phase 2
    attaches the dose state machine to button payloads, and Phase 3 attaches
    the agent to free text and voice notes.
    """
    log.debug("routing %s (kind=%s) - no handler attached yet",
              msg.wa_message_id, msg.kind)
