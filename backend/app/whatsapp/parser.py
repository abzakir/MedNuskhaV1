"""Meta webhook payload -> InboundMessage.

The InboundMessage dataclass is a frozen contract (AGENTS.md section 9).

Meta nests everything four levels deep and the message object varies by type:

    entry[0].changes[0].value.messages[0]

Button taps arrive in two different shapes and BOTH must be handled
(section 10):

    template quick reply  ->  .button.payload        (type "button")
    interactive message   ->  .interactive.button_reply.id

Both collapse to kind="button" with the payload in `payload`, so callers never
have to care which one Meta sent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

log = logging.getLogger(__name__)


@dataclass
class InboundMessage:
    """One inbound WhatsApp message, normalised."""

    wa_message_id: str
    from_number: str
    kind: Literal["text", "button", "audio", "other"]
    text: str | None
    payload: str | None
    media_id: str | None
    timestamp: datetime


@dataclass
class StatusUpdate:
    """A delivery receipt for a message we sent."""

    wa_message_id: str
    status: str
    timestamp: datetime
    recipient: str | None = None
    error: str | None = None


def _ts(raw: Any) -> datetime:
    """Meta sends unix seconds as a string."""
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _values(body: dict) -> list[dict]:
    """Every `value` object in the payload, across entries and changes."""
    out = []
    for entry in body.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value")
            if isinstance(value, dict):
                out.append(value)
    return out


def parse_message(raw: dict) -> InboundMessage:
    """Normalise one message object from the messages array."""
    msg_type = raw.get("type")
    text: str | None = None
    payload: str | None = None
    media_id: str | None = None
    kind: Literal["text", "button", "audio", "other"] = "other"

    if msg_type == "text":
        kind = "text"
        text = (raw.get("text") or {}).get("body")

    elif msg_type == "button":
        # Quick reply on a TEMPLATE message.
        kind = "button"
        button = raw.get("button") or {}
        payload = button.get("payload")
        text = button.get("text")

    elif msg_type == "interactive":
        # Quick reply on an INTERACTIVE message - different shape, same meaning.
        interactive = raw.get("interactive") or {}
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        if reply:
            kind = "button"
            payload = reply.get("id")
            text = reply.get("title")

    elif msg_type == "audio":
        kind = "audio"
        audio = raw.get("audio") or {}
        media_id = audio.get("id")
        # A true voice note has voice=true; a forwarded mp3 does not. Both are
        # transcribable, so we accept either.

    else:
        # image, document, video, location, sticker, contacts, order, system...
        kind = "other"
        blob = raw.get(msg_type) if isinstance(raw.get(msg_type), dict) else {}
        media_id = blob.get("id")
        text = (raw.get(msg_type) or {}).get("caption") if blob else None

    return InboundMessage(
        wa_message_id=raw.get("id", ""),
        from_number=raw.get("from", ""),
        kind=kind,
        text=text,
        payload=payload,
        media_id=media_id,
        timestamp=_ts(raw.get("timestamp")),
    )


def parse_webhook(body: dict) -> list[InboundMessage]:
    """Extract every inbound message from one webhook POST body.

    Returns an empty list for status-only notifications, which are the
    majority of webhook traffic.
    """
    messages: list[InboundMessage] = []
    for value in _values(body):
        for raw in value.get("messages") or []:
            try:
                parsed = parse_message(raw)
            except Exception as exc:  # noqa: BLE001 - one bad message must not
                log.warning("could not parse message %s: %s", raw.get("id"), exc)
                continue          # discard the rest of the batch
            if parsed.wa_message_id:
                messages.append(parsed)
            else:
                log.warning("inbound message with no id, skipping: %s", raw)
    return messages


def parse_statuses(body: dict) -> list[StatusUpdate]:
    """Extract delivery receipts (sent / delivered / read / failed)."""
    out: list[StatusUpdate] = []
    for value in _values(body):
        for raw in value.get("statuses") or []:
            errors = raw.get("errors") or []
            out.append(StatusUpdate(
                wa_message_id=raw.get("id", ""),
                status=raw.get("status", ""),
                timestamp=_ts(raw.get("timestamp")),
                recipient=raw.get("recipient_id"),
                error=str(errors[0]) if errors else None,
            ))
    return out


def business_phone_number_id(body: dict) -> str | None:
    """Which of our numbers this notification is about.

    Meta delivers every number on the app to the same callback URL, so this is
    how a payload meant for someone else's number is spotted.
    """
    for value in _values(body):
        pid = (value.get("metadata") or {}).get("phone_number_id")
        if pid:
            return pid
    return None
