"""The ONLY module that talks to WhatsApp (invariant 6).

Since 2026-08-22 that means the local Baileys bridge in `whatsapp-bridge/`,
not graph.facebook.com. The bridge owns the socket; this module owns the
message. Signatures are still the frozen ones from AGENTS.md section 9, so
nothing upstream - the ticker, the state machine, the agent - changed at all.

Two behaviours differ from the Meta implementation and are deliberate:

* There are no server-side templates. `send_template` renders the copy from
  i18n/strings.py locally. That is strictly better: the wording is now
  version-controlled and changeable in a commit instead of an approval queue.
* Interactive buttons are not available to non-official clients, so the bridge
  renders the options as numbered text. `send_template` still takes
  `button_payloads` and still returns which mode was used, so the caller does
  not have to care.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from typing import Any

import httpx

from app.config import settings
from app.db import session_scope
from app.i18n import strings
from app.models import Caretaker, MessageLog, Patient

log = logging.getLogger(__name__)

#: Button payloads carry the dose id (invariant 2): "TAKEN:<dose_id>".
DOSE_PAYLOAD_RE = re.compile(r"^(TAKEN|LATER|SKIP):(?P<dose_id>[0-9a-fA-F-]{36})$")

#: Maps the positional `body_vars` in the section 9 signature onto the named
#: placeholders in i18n/strings.py. Keeping the signature frozen is worth this
#: small table.
TEMPLATE_VARS: dict[str, tuple[str, ...]] = {
    "dose_reminder": ("name", "hour", "medicine", "note"),
    "dose_followup": ("name", "medicine"),
    "caretaker_alert": ("patient", "hour", "medicine"),
    "patient_optin": ("name", "caretaker"),
}

#: Which i18n button labels go with which template.
TEMPLATE_BUTTONS: dict[str, tuple[str, ...]] = {
    "dose_reminder": ("btn_taken", "btn_later"),
    "dose_followup": ("btn_taken", "btn_later"),
}

_client: httpx.AsyncClient | None = None


class WhatsAppError(RuntimeError):
    """The bridge refused, or WhatsApp is not connected."""


# --------------------------------------------------------------------------
# numbers
# --------------------------------------------------------------------------


def normalise_number(raw: str) -> str:
    """Digits only, no + and no leading zero: 923001234567 (section 10).

    Handles the three formats humans actually type for Pakistani numbers:
    +92 300 1234567, 0300 1234567, and 00923001234567.
    """
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = "92" + digits.lstrip("0")
    return digits


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def bridge_status() -> dict:
    """Ask the bridge whether WhatsApp is actually connected."""
    try:
        resp = await get_client().get(f"{settings.bridge_url}/status", timeout=5.0)
        return resp.json()
    except Exception as exc:  # noqa: BLE001 - health check reports, never raises
        return {"state": "unreachable", "error": str(exc)}


#: The one message a patient may receive before they have agreed to anything.
#: It is how you ask, so it cannot itself require an answer - and it names no
#: medicine, no dose and no condition, so a mistyped number costs one polite
#: sentence and then silence.
CONSENT_TEMPLATES = frozenset({"patient_optin"})


class NotConsented(WhatsAppError):
    """The recipient has not agreed to receive anything yet (section 4.4)."""


def may_send(number: str, template: str | None = None) -> tuple[bool, str]:
    """Whether we are allowed to send this to this number, and why not.

    Section 4.4: nothing goes to a patient who has not opted in. The check
    lives here rather than in the bridge because only the backend knows who
    has agreed - the bridge is deliberately dumb (invariant 6) and its
    ALLOWED_NUMBERS stays as a static outer net.

    This is what makes a mistyped number safe. A wrong digit is still a
    perfectly valid `patient` row, so "is this number registered" would have
    allowed it; "has a human on this handset actually replied" does not. The
    stranger gets the intro, ignores it, and never hears from us again.

    Caretakers are exempt: they registered themselves on the dashboard, and
    a missed-dose alert going out is the entire product.
    """
    number = normalise_number(number)
    if not number:
        return False, "no number"
    if not settings.database_configured:
        return True, ""

    try:
        with session_scope() as session:
            patient = session.query(Patient).filter(
                Patient.whatsapp_number == number).first()
            if patient is None:
                # A caretaker, or a number we do not know. Unknown numbers are
                # still refused by the bridge's allowlist.
                return True, ""
            if patient.stopped:
                return False, f"{patient.name} sent STOP"
            if patient.opted_in:
                return True, ""
            if template in CONSENT_TEMPLATES:
                return True, ""
            return False, (f"{patient.name} has not opted in yet - only the "
                           f"intro message may be sent")
    except Exception as exc:  # noqa: BLE001 - a broken check must not silence
        log.warning("could not check consent for %s (%s) - allowing", number, exc)
        return True, ""


async def _call(path: str, payload: dict, *, kind: str, body: str | None,
                template_name: str | None = None,
                payloads: list[str] | None = None) -> str:
    """POST to the bridge, log the outcome, return the message id."""
    to = payload["to"]
    url = f"{settings.bridge_url}{path}"

    try:
        resp = await get_client().post(url, json=payload)
    except httpx.HTTPError as exc:
        await _log_outbound(to=to, kind=kind, body=body, message_id=None,
                            template_name=template_name, payloads=payloads,
                            error=f"bridge unreachable: {exc}")
        raise WhatsAppError(
            f"WhatsApp bridge is not reachable at {settings.bridge_url}. "
            f"Start it with `make bridge` (or .\\bridge.ps1)."
        ) from exc

    data: Any
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text}

    if resp.status_code >= 300:
        detail = data.get("error", data) if isinstance(data, dict) else data
        hint = data.get("hint") if isinstance(data, dict) else None
        await _log_outbound(to=to, kind=kind, body=body, message_id=None,
                            template_name=template_name, payloads=payloads,
                            error=str(detail), raw=data if isinstance(data, dict) else None)
        raise WhatsAppError(f"{detail}{f' - {hint}' if hint else ''}")

    message_id = data.get("id") if isinstance(data, dict) else None
    await _log_outbound(to=to, kind=kind, body=body, message_id=message_id,
                        template_name=template_name, payloads=payloads,
                        raw=data if isinstance(data, dict) else None)
    log.info("sent %s to %s -> %s", kind, to, message_id)
    return message_id


# --------------------------------------------------------------------------
# message_log
# --------------------------------------------------------------------------


def _resolve_context(number: str, payloads: list[str] | None) -> dict[str, str | None]:
    """Work out who this message concerns, so message_log rows are useful.

    Section 9 signatures are frozen and carry no context arguments, so context
    is derived instead: the recipient identifies the patient or caretaker, and
    the dose id is already inside the button payload (invariant 2).
    """
    ctx: dict[str, str | None] = {
        "patient_id": None, "caretaker_id": None, "dose_event_id": None}

    dose_id: str | None = None
    for raw in payloads or []:
        m = DOSE_PAYLOAD_RE.match(raw)
        if m:
            dose_id = m.group("dose_id")
            break

    if not settings.database_configured:
        return ctx

    try:
        with session_scope() as s:
            # message_log.dose_event_id is a foreign key. A payload naming a
            # dose that does not exist would fail the whole insert and lose the
            # audit row for a message we actually sent. The payload text is
            # stored either way, so nothing is lost by dropping just the link.
            if dose_id is not None:
                from app.models import DoseEvent

                if s.get(DoseEvent, dose_id) is not None:
                    ctx["dose_event_id"] = dose_id
                else:
                    log.warning("outbound payload names dose %s, which does not "
                                "exist - logging without the link", dose_id)

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
    except Exception as exc:  # noqa: BLE001
        log.warning("message_log write failed: %s", exc)


async def _log_outbound(*, to: str, kind: str, body: str | None,
                        message_id: str | None, template_name: str | None = None,
                        payloads: list[str] | None = None,
                        error: str | None = None, raw: dict | None = None) -> None:
    ctx = await asyncio.to_thread(_resolve_context, to, payloads)
    await asyncio.to_thread(
        _write_log,
        direction="out", kind=kind, to_number=to, body=body,
        payload=payloads[0] if payloads else None,
        template_name=template_name,
        wa_message_id=message_id,
        status="sent" if message_id else "failed",
        error=error, raw=raw, **ctx,
    )


# --------------------------------------------------------------------------
# section 9 surface
# --------------------------------------------------------------------------


def render(template: str, lang: str, body_vars: list[str] | None) -> str:
    """Render a named message from i18n/strings.py (invariant 12).

    Extra or missing values are tolerated - a slightly odd message beats an
    exception in the middle of a dose reminder.
    """
    names = TEMPLATE_VARS.get(template, ())
    values = list(body_vars or [])
    kwargs = {name: (values[i] if i < len(values) else "")
              for i, name in enumerate(names)}
    return strings.t(template, lang, **kwargs).strip()


async def send_template(to: str, template: str, lang: str,
                        body_vars: list[str] | None = None,
                        button_payloads: list[str] | None = None) -> str:
    """Send one of the named messages, with its reply options.

    `lang` here is the patient's language ("ur" / "en"), not a Meta template
    language code - there is no approval queue any more.
    """
    to = normalise_number(to)
    allowed, why = await asyncio.to_thread(may_send, to, template)
    if not allowed:
        log.warning("refusing %s to %s: %s", template, to, why)
        raise NotConsented(why)
    body = render(template, lang, body_vars)

    labels = TEMPLATE_BUTTONS.get(template, ())
    if button_payloads and labels:
        buttons = [
            {"id": payload, "text": strings.button(label, lang)}
            for payload, label in zip(button_payloads, labels)
        ]
        return await _call(
            "/send/buttons",
            {"to": to, "body": body, "buttons": buttons},
            kind="template", body=body, template_name=template,
            payloads=button_payloads,
        )

    return await _call(
        "/send/text", {"to": to, "body": body},
        kind="template", body=body, template_name=template,
        payloads=button_payloads,
    )


async def send_text(to: str, body: str) -> str:
    """Send free-form text. No 24-hour window applies on this transport."""
    to = normalise_number(to)
    allowed, why = await asyncio.to_thread(may_send, to, None)
    if not allowed:
        log.warning("refusing text to %s: %s", to, why)
        raise NotConsented(why)
    return await _call("/send/text", {"to": to, "body": body},
                       kind="text", body=body)


async def send_buttons(to: str, body: str, buttons: list[tuple[str, str]]) -> str:
    """Send reply options. `buttons` is [(id, title)].

    The id comes back as the reply payload, so it carries the dose id exactly
    as a real button tap would.
    """
    to = normalise_number(to)
    payload = [{"id": bid, "text": title[:25]} for bid, title in buttons[:3]]
    return await _call(
        "/send/buttons", {"to": to, "body": body, "buttons": payload},
        kind="interactive", body=body, payloads=[b for b, _ in buttons],
    )


async def send_voice(to: str, storage_key_or_bytes: str | bytes) -> str:
    """Send a voice note.

    Accepts raw OGG/Opus bytes or an https URL. The bridge sends it with
    ptt=true, which is what makes WhatsApp render a play button instead of a
    file attachment an elderly user will never tap (invariant 7).
    """
    to = normalise_number(to)
    allowed, why = await asyncio.to_thread(may_send, to, None)
    if not allowed:
        log.warning("refusing voice note to %s: %s", to, why)
        raise NotConsented(why)

    if isinstance(storage_key_or_bytes, (bytes, bytearray)):
        audio_b64 = base64.b64encode(bytes(storage_key_or_bytes)).decode()
    elif storage_key_or_bytes.startswith(("http://", "https://")):
        resp = await get_client().get(storage_key_or_bytes)
        if resp.status_code >= 300:
            raise WhatsAppError(f"could not fetch audio: {resp.status_code}")
        audio_b64 = base64.b64encode(resp.content).decode()
    else:
        raise ValueError(
            "send_voice needs OGG/Opus bytes or an https URL. Resolve the "
            "storage key to bytes or a signed URL in voice/tts.py first."
        )

    return await _call("/send/audio", {"to": to, "audioBase64": audio_b64, "ptt": True},
                       kind="audio", body="[voice note]")


async def download_media(media_id: str) -> bytes:
    """Fetch inbound media.

    Rarely needed on this transport: the bridge already downloads audio and
    images and hands them over base64-encoded in the webhook, so nothing has
    to be fetched afterwards. Kept because it is part of the section 9
    contract, and accepts a URL for anything that arrives by reference.
    """
    if media_id.startswith(("http://", "https://")):
        resp = await get_client().get(media_id)
        if resp.status_code >= 300:
            raise WhatsAppError(f"media download failed: {resp.status_code}")
        return resp.content
    raise WhatsAppError(
        "the Baileys bridge delivers media inline as base64 - there is no id "
        "to fetch later. Use InboundMessage.media_bytes."
    )
