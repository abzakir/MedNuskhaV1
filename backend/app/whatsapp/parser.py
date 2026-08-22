"""Meta webhook payload -> InboundMessage.

The InboundMessage dataclass is a frozen contract (AGENTS.md section 9); the
parsing itself lands in Phase 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

_PHASE = "Phase 1 - WhatsApp transport"


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


def parse_webhook(body: dict) -> list[InboundMessage]:
    """Extract every message from one webhook POST body.

    Button taps arrive in two different shapes and both must be handled
    (section 10):
      - from templates:    entry[0].changes[0].value.messages[0].button.payload
      - from interactive:  ...messages[0].interactive.button_reply.id
    """
    raise NotImplementedError(_PHASE)
