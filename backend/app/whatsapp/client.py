"""The ONLY module permitted to call graph.facebook.com (invariant 6).

Signatures are frozen in AGENTS.md section 9.

Every request and response shape here was taken from Meta's Cloud API
reference on 2026-08-22, not from memory (section 12). The shapes are also
recorded in PROJECT_LOG.md under Gotchas so a later session need not re-fetch:

    POST {base}/{PHONE_NUMBER_ID}/messages
    Authorization: Bearer <token>;  Content-Type: application/json
    -> 200 {"messages": [{"id": "wamid...."}], ...}

Numbers go out as digits only, no + and no leading zero (section 10).
Every send is written to message_log, success or failure.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from app.config import settings
from app.db import session_scope
from app.models import Caretaker, MessageLog, Patient

log = logging.getLogger(__name__)

#: Button payloads carry the dose id (invariant 2): "TAKEN:<dose_id>".
DOSE_PAYLOAD_RE = re.compile(r"^(TAKEN|LATER|SKIP):(?P<dose_id>[0-9a-fA-F-]{36})$")

_client: httpx.AsyncClient | None = None


class WhatsAppError(RuntimeError):
    """A non-2xx response from Meta, carrying whatever detail Meta gave us."""

    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body
        detail = body
        if isinstance(body, dict):
            err = body.get("error", {})
            detail = f"{err.get('code')}/{err.get('error_subcode')} {err.get('message')}"
        super().__init__(f"WhatsApp API {status}: {detail}")


# --------------------------------------------------------------------------
# numbers
# --------------------------------------------------------------------------


def normalise_number(raw: str) -> str:
    """Digits only, no + and no leading zero, e.g. 923001234567 (section 10).

    Handles the three formats humans actually type for Pakistani numbers:
    +92 300 1234567, 0300 1234567, and 00923001234567.
    """
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    # A local Pakistani mobile: 03xxxxxxxxx -> 923xxxxxxxxx
    if digits.startswith("0"):
        digits = "92" + digits.lstrip("0")
    return digits


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------


def _require_config() -> None:
    if not settings.whatsapp_configured:
        raise WhatsAppError(
            0,
            "WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID are not set. "
            "Fill them in .env - see MedNuskha_Setup_Guide.pdf section 2.",
        )


def get_client() -> httpx.AsyncClient:
    """One shared async client for the process."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0))
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _base() -> str:
    return f"https://graph.facebook.com/{settings.whatsapp_api_version}"


def _messages_url() -> str:
    return f"{_base()}/{settings.whatsapp_phone_number_id}/messages"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.whatsapp_token}",
        "Content-Type": "application/json",
    }


# --------------------------------------------------------------------------
# message_log
# --------------------------------------------------------------------------


def _resolve_context(number: str, payloads: list[str] | None) -> dict[str, str | None]:
    """Work out who this message concerns, so message_log rows are useful.

    Signatures in section 9 are frozen and carry no context arguments, so the
    context is derived instead: the recipient identifies the patient or
    caretaker, and the dose id is already inside the button payload
    (invariant 2) whenever there is one.
    """
    ctx: dict[str, str | None] = {
        "patient_id": None,
        "caretaker_id": None,
        "dose_event_id": None,
    }

    for raw in payloads or []:
        m = DOSE_PAYLOAD_RE.match(raw)
        if m:
            ctx["dose_event_id"] = m.group("dose_id")
            break

    if not settings.database_configured:
        return ctx

    try:
        with session_scope() as s:
            patient = s.query(Patient).filter(Patient.whatsapp_number == number).first()
            if patient:
                ctx["patient_id"] = patient.id
                return ctx
            caretaker = s.query(Caretaker).filter(Caretaker.phone == number).first()
            if caretaker:
                ctx["caretaker_id"] = caretaker.id
    except Exception as exc:  # noqa: BLE001 - logging must never break a send
        log.warning("could not resolve context for %s: %s", number, exc)
    return ctx


def _write_log(**fields) -> None:
    try:
        with session_scope() as s:
            s.add(MessageLog(**fields))
            s.commit()
    except Exception as exc:  # noqa: BLE001 - never let logging break a send
        log.warning("message_log write failed: %s", exc)


async def _log_outbound(
    *,
    to: str,
    kind: str,
    body: str | None,
    wa_message_id: str | None,
    template_name: str | None = None,
    payloads: list[str] | None = None,
    error: str | None = None,
    raw: dict | None = None,
) -> None:
    ctx = await asyncio.to_thread(_resolve_context, to, payloads)
    await asyncio.to_thread(
        _write_log,
        direction="out",
        kind=kind,
        to_number=to,
        body=body,
        payload=payloads[0] if payloads else None,
        template_name=template_name,
        wa_message_id=wa_message_id,
        status="sent" if wa_message_id else "failed",
        error=error,
        raw=raw,
        **ctx,
    )


async def _post(payload: dict, *, kind: str, body: str | None,
                template_name: str | None = None,
                payloads: list[str] | None = None) -> str:
    """POST to /messages, log the outcome, return Meta's wa_message_id."""
    _require_config()
    to = payload["to"]

    try:
        resp = await get_client().post(_messages_url(), headers=_headers(), json=payload)
    except httpx.HTTPError as exc:
        await _log_outbound(to=to, kind=kind, body=body, wa_message_id=None,
                            template_name=template_name, payloads=payloads,
                            error=str(exc))
        log.error("send to %s failed: %s", to, exc)
        raise WhatsAppError(0, str(exc)) from exc

    try:
        data = resp.json()
    except ValueError:
        data = {"raw_text": resp.text}

    if resp.status_code >= 300:
        await _log_outbound(to=to, kind=kind, body=body, wa_message_id=None,
                            template_name=template_name, payloads=payloads,
                            error=str(data), raw=data)
        raise WhatsAppError(resp.status_code, data)

    wamid = (data.get("messages") or [{}])[0].get("id")
    await _log_outbound(to=to, kind=kind, body=body, wa_message_id=wamid,
                        template_name=template_name, payloads=payloads, raw=data)
    log.info("sent %s to %s -> %s", kind, to, wamid)
    return wamid


# --------------------------------------------------------------------------
# section 9 surface
# --------------------------------------------------------------------------


async def send_template(
    to: str,
    template: str,
    lang: str,
    body_vars: list[str] | None = None,
    button_payloads: list[str] | None = None,
) -> str:
    """Send an approved UTILITY template. Returns Meta's wa_message_id.

    Every dose reminder goes through here (invariant 1). `button_payloads`
    carries the dose id, e.g. "TAKEN:<dose_id>" / "LATER:<dose_id>"
    (invariant 2), and maps positionally onto the template's quick-reply
    buttons - index 0 is the first button defined in Business Manager.

    Meta allows at most three dynamic button payloads per template.
    """
    to = normalise_number(to)
    components: list[dict] = []

    if body_vars:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": str(v)} for v in body_vars],
        })

    for index, payload in enumerate(button_payloads or []):
        if index > 2:
            log.warning("template %s: dropping button payload %d (Meta allows 3)",
                        template, index)
            break
        components.append({
            "type": "button",
            "sub_type": "quick_reply",
            "index": index,
            "parameters": [{"type": "payload", "payload": payload}],
        })

    message: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {"name": template, "language": {"code": lang}},
    }
    if components:
        message["template"]["components"] = components

    return await _post(
        message,
        kind="template",
        body=f"[{template}] " + " | ".join(str(v) for v in (body_vars or [])),
        template_name=template,
        payloads=button_payloads,
    )


async def send_text(to: str, body: str) -> str:
    """Send free-form text.

    Only delivers inside an open 24-hour customer service window (invariant 1);
    outside it Meta accepts the call but the message never arrives.
    """
    to = normalise_number(to)
    return await _post(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        },
        kind="text",
        body=body,
    )


async def send_buttons(to: str, body: str, buttons: list[tuple[str, str]]) -> str:
    """Send an interactive reply-button message. `buttons` is [(id, title)].

    The id comes back as interactive.button_reply.id, so it carries the dose
    payload exactly like a template quick reply does. Meta allows three
    buttons and titles are capped at 20 characters.
    """
    to = normalise_number(to)
    return await _post(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": bid, "title": title[:20]}}
                        for bid, title in buttons[:3]
                    ]
                },
            },
        },
        kind="interactive",
        body=body,
        payloads=[bid for bid, _ in buttons],
    )


async def send_voice(to: str, storage_key_or_bytes: str | bytes) -> str:
    """Send a voice note.

    Accepts raw OGG/Opus bytes (uploaded to Meta first), an https URL, or a
    Meta media id. Audio must be **audio/ogg with the OPUS codec, mono** -
    Meta rejects plain ogg, and anything else renders as a file attachment
    that elderly users will not open (invariant 7).

    A Supabase storage key is not resolved here: keeping storage out of this
    module is what invariant 6 is for. voice/tts.py hands over bytes or a
    signed URL.
    """
    to = normalise_number(to)
    audio: dict[str, str]

    if isinstance(storage_key_or_bytes, (bytes, bytearray)):
        media_id = await upload_media(bytes(storage_key_or_bytes), "audio/ogg")
        audio = {"id": media_id}
    elif storage_key_or_bytes.startswith(("http://", "https://")):
        audio = {"link": storage_key_or_bytes}
    elif storage_key_or_bytes.isdigit():
        audio = {"id": storage_key_or_bytes}
    else:
        raise ValueError(
            "send_voice needs OGG/Opus bytes, an https URL, or a Meta media id. "
            f"Got {storage_key_or_bytes!r} - resolve the storage key to a signed "
            "URL or bytes in voice/tts.py first."
        )

    return await _post(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "audio",
            "audio": audio,
        },
        kind="audio",
        body="[voice note]",
    )


async def upload_media(data: bytes, mime_type: str = "audio/ogg") -> str:
    """Upload media to Meta and return its media id.

    POST {base}/{PHONE_NUMBER_ID}/media, multipart/form-data, with fields
    messaging_product=whatsapp, type, file. Media ids expire after 30 days.
    """
    _require_config()
    url = f"{_base()}/{settings.whatsapp_phone_number_id}/media"
    ext = "ogg" if "ogg" in mime_type else mime_type.split("/")[-1]

    resp = await get_client().post(
        url,
        headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
        data={"messaging_product": "whatsapp", "type": mime_type},
        files={"file": (f"voice.{ext}", data, mime_type)},
    )
    if resp.status_code >= 300:
        raise WhatsAppError(resp.status_code, _safe_json(resp))

    media_id = resp.json().get("id")
    log.info("uploaded %d bytes of %s -> media %s", len(data), mime_type, media_id)
    return media_id


async def download_media(media_id: str) -> bytes:
    """Download inbound media.

    Two steps (section 10). GET {base}/{media_id} returns a url that is valid
    for five minutes, then that url must be fetched **with the Bearer token
    attached** - Meta returns 401 for a plain fetch.
    """
    _require_config()
    client = get_client()
    auth = {"Authorization": f"Bearer {settings.whatsapp_token}"}

    meta_resp = await client.get(f"{_base()}/{media_id}", headers=auth)
    if meta_resp.status_code >= 300:
        raise WhatsAppError(meta_resp.status_code, _safe_json(meta_resp))

    meta = meta_resp.json()
    url = meta.get("url")
    if not url:
        raise WhatsAppError(meta_resp.status_code, f"no url in media response: {meta}")

    binary = await client.get(url, headers=auth)
    if binary.status_code >= 300:
        raise WhatsAppError(binary.status_code, _safe_json(binary))

    log.info("downloaded media %s (%s, %d bytes)",
             media_id, meta.get("mime_type"), len(binary.content))
    return binary.content


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text
