"""The ONLY module permitted to call graph.facebook.com (invariant 6).

Signatures are frozen in AGENTS.md section 9. Implemented in Phase 1, after
fetching Meta's current Cloud API reference - field names are never written
from memory (section 12).

Base URL: https://graph.facebook.com/{version}/{PHONE_NUMBER_ID}/messages
Numbers are sent with no + and no leading zero: 923001234567 (section 10).
"""

from __future__ import annotations

_PHASE = "Phase 1 - WhatsApp transport"


async def send_template(
    to: str,
    template: str,
    lang: str,
    body_vars: list[str],
    button_payloads: list[str] | None = None,
) -> str:
    """Send an approved UTILITY template. Returns Meta's wa_message_id.

    Every dose reminder goes through here (invariant 1). `button_payloads`
    carries the dose id, e.g. "TAKEN:<dose_id>" / "LATER:<dose_id>"
    (invariant 2).
    """
    raise NotImplementedError(_PHASE)


async def send_text(to: str, body: str) -> str:
    """Send free-form text. Only valid inside an open 24-hour service window."""
    raise NotImplementedError(_PHASE)


async def send_buttons(to: str, body: str, buttons: list[tuple[str, str]]) -> str:
    """Send an interactive reply-button message. `buttons` is [(id, title)]."""
    raise NotImplementedError(_PHASE)


async def send_voice(to: str, storage_key_or_bytes: str | bytes) -> str:
    """Send a voice note. Must be OGG/Opus (invariant 7) or elderly users see
    a file attachment they will not open."""
    raise NotImplementedError(_PHASE)


async def download_media(media_id: str) -> bytes:
    """Download inbound media.

    Two steps (section 10): GET /{version}/{media_id} for a URL, then fetch
    that URL with the Bearer token attached. A plain fetch returns 401.
    """
    raise NotImplementedError(_PHASE)
