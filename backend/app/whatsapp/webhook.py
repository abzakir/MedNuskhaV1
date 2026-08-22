"""Meta webhook endpoints: GET verify, POST receive.

Invariant 3: POST returns HTTP 200 within 2 seconds, BEFORE any processing.
Work is handed to a background task; nothing slow happens inline.
Invariant 4: every inbound message is deduplicated on wa_message_id via the
unique index on message_log.
"""

from __future__ import annotations

from fastapi import APIRouter

_PHASE = "Phase 1 - WhatsApp transport"

router = APIRouter(tags=["whatsapp"])


@router.get("/webhook")
async def verify_webhook():
    """Meta's subscription handshake.

    Returns hub.challenge as PLAIN TEXT, not JSON (section 10), when
    hub.verify_token matches WHATSAPP_VERIFY_TOKEN.
    """
    raise NotImplementedError(_PHASE)


@router.post("/webhook")
async def receive_webhook():
    """Accept an inbound webhook, enqueue it, return 200 immediately."""
    raise NotImplementedError(_PHASE)
