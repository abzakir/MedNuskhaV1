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

import asyncio
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
# GET /webhook - liveness only
# --------------------------------------------------------------------------


@router.get("/webhook", response_class=PlainTextResponse)
async def webhook_alive() -> PlainTextResponse:
    """Confirms the endpoint is reachable.

    Meta needed a hub.challenge handshake here; the Baileys bridge does not.
    Kept so a human can check the URL in a browser.
    """
    return PlainTextResponse("mednuskha webhook ok")


# --------------------------------------------------------------------------
# POST /webhook - inbound messages and delivery receipts
# --------------------------------------------------------------------------


@router.post("/webhook")
@router.post("/webhook/{secret}")
async def receive_webhook(request: Request, background: BackgroundTasks,
                          secret: str | None = None) -> Response:
    """Accept an inbound message, enqueue it, return 200 immediately.

    Nothing is parsed here on purpose (invariant 3): the bridge retries a
    failed forward, and slow processing here would cost us messages.

    The endpoint is public, so anyone who guesses the URL could post a fake
    "patient took her medicine". WEBHOOK_SECRET is required in the path when
    it is configured, which is what stops that.
    """
    expected = settings.webhook_secret
    if expected and secret != expected:
        log.warning("webhook rejected: bad or missing secret in path")
        return Response(status_code=403)

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


async def process_webhook(body: dict) -> None:
    """Parse and persist one webhook body. Runs after the 200 has been sent."""
    try:
        messages = parse_webhook(body)
        statuses = parse_statuses(body)
    except Exception as exc:  # noqa: BLE001 - never crash the background task
        log.exception("webhook parse failed: %s", exc)
        return

    for status in statuses:
        try:
            await asyncio.to_thread(_apply_status, status)
        except Exception as exc:  # noqa: BLE001
            log.warning("status update failed for %s: %s", status.wa_message_id, exc)

    for msg in messages:
        try:
            routed = await asyncio.to_thread(_process_message, msg, body)
            if routed:
                await _route(msg, routed)
        except Exception as exc:  # noqa: BLE001 - one bad message must not
            log.exception("inbound %s failed: %s", msg.wa_message_id, exc)


def _process_message(msg: InboundMessage, raw_body: dict) -> dict | None:
    """Persist one inbound message, deduplicating on wa_message_id.

    Returns the routing context when the message is new and comes from a
    number we know, or None when there is nothing further to do.
    """
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
            # We are the recipient; the bridge's own number is a runtime
            # fact, not configuration, and nothing downstream reads it.
            to_number=None,
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
            return None

        context = {
            "patient_id": patient.id if patient else None,
            "patient_name": patient.name if patient else None,
            "caretaker_id": caretaker.id if caretaker else None,
            "number": number,
        }

    who = patient.name if patient else (caretaker.name if caretaker else "unknown")
    log.info("inbound %s from %s (%s): kind=%s payload=%s text=%r",
             msg.wa_message_id, number, who, msg.kind, msg.payload, msg.text)

    if patient is None and caretaker is None:
        log.warning("inbound from an unregistered number %s - ignoring", number)
        return None

    return context


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


async def _route(msg: InboundMessage, context: dict) -> None:
    """Hand a persisted message on to whoever owns it.

    A button payload goes straight to the dose state machine - no
    interpretation is needed, because the dose id is right there in the
    payload (invariant 2). Free text and voice notes are the agent's job and
    are attached in Phase 3.
    """
    if msg.kind == "button" and msg.payload:
        await handle_button(msg, context)
        return

    log.debug("no handler yet for kind=%s from %s (Phase 3 attaches the agent)",
              msg.kind, context["number"])


async def handle_button(msg: InboundMessage, context: dict) -> None:
    """Apply a quick-reply tap to the dose it names."""
    from app.scheduler import state_machine as sm
    from app.scheduler.ticker import notify_late_resolution
    from app.whatsapp.client import DOSE_PAYLOAD_RE

    match = DOSE_PAYLOAD_RE.match(msg.payload or "")
    if not match:
        log.info("button payload %r carries no dose id - ignoring", msg.payload)
        return

    action, dose_id = match.group(1), match.group("dose_id")

    if action == "TAKEN":
        landed = await asyncio.to_thread(
            sm.confirm_taken, dose_id, "button", msg.text)
        if landed == "TAKEN_LATE":
            # Section 4.8: a late confirmation must reach the caretaker who
            # was already told the dose was missed.
            await notify_late_resolution(dose_id)

    elif action == "SKIP":
        await asyncio.to_thread(sm.mark_skipped, dose_id, msg.text, "button")

    elif action == "LATER":
        # "Abhi nahi" acknowledges the reminder but is NOT a snooze - snoozing
        # beyond it is explicitly out of scope (section 4). The dose stays
        # open so the follow-up and the caretaker escalation still run.
        await asyncio.to_thread(_record_later, dose_id, msg.text)
        log.info("dose %s: patient replied 'abhi nahi' - chain continues",
                 dose_id)


def _record_later(dose_id: str, text: str | None) -> None:
    """Store an "abhi nahi" reply without changing state.

    Deliberately not in state_machine.py: nothing here touches `state`, and
    section 8 reserves that module for transitions only.
    """
    with session_scope() as session:
        dose = session.get(DoseEvent, dose_id)
        if dose is None:
            return
        dose.response_text = text
        dose.reason = text or "abhi nahi"
        session.add(dose)
        session.commit()
