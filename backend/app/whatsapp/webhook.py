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

    if context.get("patient_id") is None:
        if context.get("caretaker_id") and msg.kind in ("text", "audio"):
            await handle_caretaker_message(msg, context)
        else:
            log.info("ignoring %s from caretaker %s",
                     msg.kind, context.get("caretaker_id"))
        return

    if msg.kind in ("text", "audio"):
        await handle_patient_reply(msg, context)
        return

    log.info("ignoring %s message from %s", msg.kind, context["number"])


async def handle_caretaker_message(msg: InboundMessage, context: dict) -> None:
    """The caretaker asking us something, by text or by voice note.

    A voice note is transcribed and then treated identically - the caretaker
    may be driving, or may simply find it faster.
    """
    from app.agent import caretaker as care

    row = await asyncio.to_thread(_load_caretaker, context["caretaker_id"])
    if row is None:
        return

    text = msg.text or ""
    if msg.kind == "audio":
        from app.voice import asr

        audio = getattr(msg, "media_bytes", None)
        if not audio:
            log.warning("caretaker audio %s arrived with no audio",
                        msg.wa_message_id)
            return
        text = await asr.transcribe(audio, language=row["language"] or "ur")
        await asyncio.to_thread(_store_transcript, msg.wa_message_id, text)
        log.info("caretaker voice note transcribed: %r", text[:80])

    await care.handle(text, row)


def _load_caretaker(caretaker_id: str) -> dict | None:
    with session_scope() as session:
        row = session.get(Caretaker, caretaker_id)
        if row is None:
            return None
        return {"id": row.id, "name": row.name, "phone": row.phone,
                "language": row.language}


async def handle_patient_reply(msg: InboundMessage, context: dict) -> None:
    """Typed or spoken reply -> Intent -> action -> one warm message back.

    A voice note is transcribed first and then treated exactly like a typed
    message, which is the whole point of section 14's Phase 5: voice is a
    doorway, not a separate code path.
    """
    from app.agent import respond as responder
    from app.agent.interpret import interpret

    patient = await asyncio.to_thread(_load_patient, context["patient_id"])
    if patient is None:
        return

    text = msg.text or ""
    from_voice = False

    if msg.kind == "audio":
        from app.voice import asr

        audio = getattr(msg, "media_bytes", None)
        if not audio:
            log.warning("audio message %s arrived with no audio", msg.wa_message_id)
            return
        text = await asr.transcribe(audio, language=patient.language or "ur")
        from_voice = True
        await asyncio.to_thread(_store_transcript, msg.wa_message_id, text)
        if not text:
            log.warning("could not transcribe %s - asking the patient to repeat",
                        msg.wa_message_id)

    open_doses = await asyncio.to_thread(responder.open_doses_for, patient.id)
    log.info("patient %s has %d open dose(s)", patient.id, len(open_doses))

    probe = _Probe(text=text, payload=msg.payload,
                   forwarded=getattr(msg, "forwarded", False))
    intent = await interpret(probe, patient, open_doses)
    intent.from_voice = from_voice

    await responder.respond(intent, patient)


class _Probe:
    """The minimal shape `interpret` needs, so a transcript can stand in for
    the original message without mutating it."""

    __slots__ = ("text", "payload", "forwarded")

    def __init__(self, text: str | None, payload: str | None,
                 forwarded: bool = False):
        self.text = text
        self.payload = payload
        #: Carried through so a forwarded voice note is not read as an
        #: answer once it has been transcribed - see agent.interpret.
        self.forwarded = forwarded


def _load_patient(patient_id: str):
    with session_scope() as session:
        patient = session.get(Patient, patient_id)
        if patient is None:
            return None
        session.expunge(patient)
        return patient


def _store_transcript(wa_message_id: str, text: str) -> None:
    """Keep the transcript on the message row, so a bad one is debuggable."""
    with session_scope() as session:
        row = session.query(MessageLog).filter(
            MessageLog.wa_message_id == wa_message_id).first()
        if row is None:
            return
        row.body = text or row.body
        session.add(row)
        session.commit()


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
