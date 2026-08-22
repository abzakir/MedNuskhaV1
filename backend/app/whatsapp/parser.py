"""Bridge payload -> InboundMessage.

The InboundMessage dataclass is a frozen contract (AGENTS.md section 9); only
what feeds it changed when the transport moved to the Baileys bridge on
2026-08-22.

The bridge does the messy part - unwrapping Baileys' protobuf message types,
downloading media - and hands over one flat shape:

    { id, from, timestamp, type, text, buttonId, audioBase64, imageBase64, raw }

`media_bytes` is new. Baileys delivers media inline rather than as an id to
fetch later, so a voice note arrives complete and there is no second round
trip and no expiring URL to race.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

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

    #: The media itself, already downloaded by the bridge. None for text.
    media_bytes: bytes | None = field(default=None, repr=False)
    #: Whatever the bridge could tell us about the original message.
    raw: dict = field(default_factory=dict)

    @property
    def has_media(self) -> bool:
        return bool(self.media_bytes)


@dataclass
class StatusUpdate:
    """A delivery receipt. The bridge does not emit these today; the shape
    exists so webhook.py needs no change if it starts to."""

    wa_message_id: str
    status: str
    timestamp: datetime
    recipient: str | None = None
    error: str | None = None


def _ts(raw) -> datetime:
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _decode(value: str | None) -> bytes | None:
    if not value:
        return None
    try:
        return base64.b64decode(value)
    except Exception as exc:  # noqa: BLE001 - a bad blob must not lose the message
        log.warning("could not decode inline media: %s", exc)
        return None


#: Bridge type -> the four kinds section 9 allows.
_KINDS: dict[str, str] = {
    "text": "text",
    "button": "button",
    "audio": "audio",
    "image": "other",
    "other": "other",
}


def parse_message(body: dict) -> InboundMessage:
    """Normalise one message from the bridge."""
    kind = _KINDS.get(body.get("type", "other"), "other")

    media = _decode(body.get("audioBase64")) or _decode(body.get("imageBase64"))

    return InboundMessage(
        wa_message_id=str(body.get("id") or ""),
        from_number=str(body.get("from") or ""),
        kind=kind,  # type: ignore[arg-type]
        text=body.get("text"),
        # A tapped option and a typed reply arrive by different routes but mean
        # the same thing to everything downstream (invariant 2).
        payload=body.get("buttonId"),
        media_id=body.get("mediaId"),
        timestamp=_ts(body.get("timestamp")),
        media_bytes=media,
        raw=body.get("raw") or {},
    )


def parse_webhook(body: dict) -> list[InboundMessage]:
    """Extract every inbound message from one bridge POST.

    The bridge posts one message per request, but a list is accepted too so
    batching can be added later without touching the caller.
    """
    if not isinstance(body, dict):
        return []

    if isinstance(body.get("messages"), list):
        raw_messages = body["messages"]
    elif body.get("id"):
        raw_messages = [body]
    else:
        return []

    out: list[InboundMessage] = []
    for raw in raw_messages:
        try:
            parsed = parse_message(raw)
        except Exception as exc:  # noqa: BLE001 - one bad message must not
            log.warning("could not parse %s: %s", raw.get("id"), exc)
            continue                                    # discard the batch
        if parsed.wa_message_id and parsed.from_number:
            out.append(parsed)
        else:
            log.warning("message with no id or sender, skipping: %s", raw)
    return out


def parse_statuses(body: dict) -> list[StatusUpdate]:
    """Delivery receipts. The bridge does not send these yet."""
    out: list[StatusUpdate] = []
    for raw in (body or {}).get("statuses") or []:
        out.append(StatusUpdate(
            wa_message_id=raw.get("id", ""),
            status=raw.get("status", ""),
            timestamp=_ts(raw.get("timestamp")),
            recipient=raw.get("recipient"),
            error=raw.get("error"),
        ))
    return out
