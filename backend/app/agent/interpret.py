"""Turn a messy human reply into exactly one Intent (AGENTS.md section 11).

Understands Urdu script, Roman Urdu and English. Runs on a Qwen model through
`agent.llm`, which pools several API keys so one hitting its daily cap does not
take the agent down mid-demo.

Always called from a background task, never on the webhook request path -
model latency inside the webhook would cost us the fast 200 (section 17).

## Which dose a reply refers to

Section 5.2 said the dose id travels in the button payload and must never be
inferred from timing. WhatsApp then removed interactive buttons for
non-official clients, so there is no payload any more (see PROJECT_LOG,
2026-08-23). The replacement rule, in order:

1. If a payload IS present, use it. Nothing beats an explicit id.
2. Otherwise look only at doses actually AWAITING an answer for this patient.
3. Exactly one open -> unambiguous, use it.
4. Several open -> match on the medicine name in the reply, which is why every
   reminder names the medicine.
5. Still ambiguous -> return `unclear` and ask one short question naming the
   options. Never guess.

That is resolving against real pending state, not reading the clock.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

from app.agent import guardrails, llm

log = logging.getLogger(__name__)

#: Below this, interpret returns "unclear" and respond asks one clarifying
#: question. The agent never guesses (section 11).
CONFIDENCE_FLOOR = 0.6

IntentKind = Literal["taken", "not_taken", "later", "question",
                     "symptom", "emergency", "unclear", "stop"]


@dataclass
class Intent:
    """What the patient meant, and which dose it refers to."""

    kind: IntentKind
    dose_id: str | None
    reason: str | None
    confidence: float
    #: Which medicine the patient named, if any. Used to pick between doses.
    medicine: str | None = None
    #: The text the intent was derived from - the typed message, or the
    #: transcript of a voice note.
    text: str | None = None
    #: WhatsApp said the message was forwarded, not composed now.
    forwarded: bool = False


# --------------------------------------------------------------------------
# fast paths - no model call needed
# --------------------------------------------------------------------------

#: Unambiguous confirmations. Matching these saves a model call on the single
#: most common reply in the whole system, and works even if every key is down.
_TAKEN_RE = re.compile(
    r"(^|\b)("
    r"haan|han|ha|jee|ji\s*haan|yes|yep|yeah|ok|okay|theek|thik|done|"
    r"le\s*li|leli|le\s*liya|lelia|le\s*chuka|le\s*chuki|kha\s*li|khali|"
    r"kha\s*liya|pi\s*li|taken|took\s*it|had\s*it|already\s*took"
    r")(\b|$)|"
    r"لے\s*لی|لی\s*ہے|کھا\s*لی|ہاں|جی\s*ہاں|پی\s*لی",
    re.IGNORECASE,
)

_LATER_RE = re.compile(
    r"(^|\b)(abhi\s*nahi|abi\s*nahi|abhi\s*nhi|baad\s*mein|baad\s*me|later|"
    r"not\s*yet|not\s*now|thori\s*der|thodi\s*der|wait)(\b|$)|"
    r"ابھی\s*نہیں|بعد\s*میں",
    re.IGNORECASE,
)

_STOP_RE = re.compile(
    r"(^|\b)(stop|band\s*kar|band\s*karo|band\s*kardo|unsubscribe|"
    r"mat\s*bhejo|na\s*bhejo|bas\s*karo)(\b|$)|بند\s*کر|مت\s*بھیجو",
    re.IGNORECASE,
)

_QUESTION_RE = re.compile(
    r"(\?|\bkis\s*liye\b|\bkyun\b|\bkyu\b|\bkia\s*hai\b|\bkya\s*hai\b|"
    r"\bwhat\s*is\b|\bwhat'?s\s*this\b|\bwhy\b|\bkis\s*ke\s*liye\b)|"
    r"کس\s*لیے|کیوں|کیا\s*ہے",
    re.IGNORECASE,
)

#: "1" / "2" replies to the numbered options the bridge sends in place of
#: buttons. Option order is fixed by TEMPLATE_BUTTONS in whatsapp/client.py.
_OPTION_RE = re.compile(r"^\s*([12])\s*[.)]?\s*$")


def is_affirmative(text: str) -> bool:
    """True when a short reply is a plain yes.

    Used by the opt-in path, which asks one closed question and needs the
    answer to it - not a dose confirmation. Kept next to `_TAKEN_RE` so the
    two can never drift apart: "HAAN" is what the opt-in message asks for and
    is the same word a patient uses to confirm a dose.
    """
    clean = (text or "").strip()
    if not clean or len(clean.split()) > 4:
        return False
    return bool(_TAKEN_RE.search(clean))


def _fast_intent(text: str) -> tuple[IntentKind, float] | None:
    """Classify the obvious replies without spending a model call."""
    clean = (text or "").strip()
    if not clean:
        return None

    option = _OPTION_RE.match(clean)
    if option:
        return ("taken", 0.95) if option.group(1) == "1" else ("later", 0.95)

    if guardrails.is_emergency(clean):
        return ("emergency", 0.99)
    if _STOP_RE.search(clean):
        return ("stop", 0.95)

    # A question wins over a bare "haan", because "haan, yeh kis liye hai?"
    # is a question, not a confirmation.
    if _QUESTION_RE.search(clean):
        return None                      # let the model handle it properly

    # Only trust a keyword match on a SHORT message. "le li" inside a long
    # sentence may well be "abhi tak nahi le li".
    if len(clean.split()) <= 4:
        if _LATER_RE.search(clean):
            return ("later", 0.9)
        if _TAKEN_RE.search(clean):
            return ("taken", 0.9)
    return None


# --------------------------------------------------------------------------
# dose resolution
# --------------------------------------------------------------------------


def _medicine_in_text(text: str, open_doses: list) -> str | None:
    """Which of the patient's open medicines the reply names, if any."""
    lowered = (text or "").lower()
    for dose in open_doses:
        name = (getattr(dose, "medicine_name", "") or "").lower()
        if not name:
            continue
        for word in name.split():
            if len(word) >= 4 and word in lowered:
                return getattr(dose, "id", None)
    return None


#: Intents that change what the record says happened. A forwarded message
#: may never produce one of these - see `_not_an_answer`.
STATE_CHANGING = ("taken", "not_taken", "later", "stop")


def _not_an_answer(kind: IntentKind, forwarded: bool) -> bool:
    """True when a forwarded message is about to be read as a reply.

    A patient forwarding a voice note is passing something along, not
    answering us. On 2026-08-30 one forwarded her own note back and the
    agent recorded the dose as taken and thanked her for it - a dose
    marked swallowed that nobody had swallowed, and the escalation that
    would have caught it switched off.

    Nothing that changes the record may come from a forwarded message.
    An emergency still does: erring towards alerting somebody is the one
    direction this system is allowed to err in, and a forwarded "seene
    mein dard" is still worth a human looking.
    """
    return forwarded and kind in STATE_CHANGING


#: States where the patient has actually been asked and has not answered.
AWAITING_STATES = ("SENT", "AWAITING_REPLY", "REMINDED_AGAIN")


def resolve_dose(text: str, payload: str | None, open_doses: list
                 ) -> tuple[str | None, bool]:
    """Work out which dose a reply is about.

    Returns (dose_id, ambiguous). `ambiguous` True means the reply genuinely
    could be about more than one dose, and the caller must ask rather than
    pick.

    A MISSED dose is deliberately NOT treated as competing with one that is
    still awaiting an answer. Missed doses accumulate - by the second day a
    patient has several - and counting them made every single reply ambiguous,
    so the agent answered "samajh nahi aaya" to everything. Observed on a real
    phone, 2026-08-23. A missed dose only matters when nothing else is open,
    and then only for a late confirmation.
    """
    if payload:
        from app.whatsapp.client import DOSE_PAYLOAD_RE

        match = DOSE_PAYLOAD_RE.match(payload)
        if match:
            return match.group("dose_id"), False

    if not open_doses:
        return None, False

    awaiting = [d for d in open_doses
                if getattr(d, "state", None) in AWAITING_STATES]
    candidates = awaiting or open_doses      # fall back to MISSED ones

    if len(candidates) == 1:
        return getattr(candidates[0], "id", None), False

    named = _medicine_in_text(text, candidates)
    if named:
        return named, False

    # Several are genuinely waiting. The most recent is the one they were just
    # reminded about, but we do not assume - we ask.
    log.info("%d doses awaiting a reply and none named - asking rather than "
             "guessing", len(candidates))
    return None, True


# --------------------------------------------------------------------------
# the model
# --------------------------------------------------------------------------

_SYSTEM = """You classify one WhatsApp reply from an elderly Pakistani patient \
who was reminded to take a medicine. The reply may be Urdu script, Roman Urdu, \
English, or a mix, and may be a transcript of a voice note, so spelling is \
often wrong.

Choose exactly one kind:
- taken: they took the medicine
- not_taken: they did NOT take it and gave a reason (finished the strip, cannot \
find it, feeling too unwell)
- later: they will take it shortly ("abhi nahi", "baad mein")
- question: they are asking something about the medicine
- symptom: they mention feeling unwell, but it is not an emergency
- emergency: chest pain, cannot breathe, unconscious, bleeding
- stop: they want the reminders to end
- unclear: you genuinely cannot tell

Also extract:
- medicine: the medicine name they mention, or null
- reason: their stated reason in THEIR OWN WORDS, or null. Never paraphrase - \
this is quoted verbatim in a report for a doctor.
- confidence: 0 to 1. Be honest. A garbled transcript deserves a low number.

Return ONLY JSON:
{"kind": str, "medicine": str|null, "reason": str|null, "confidence": float}
"""


async def interpret(msg, patient, open_doses) -> Intent:
    """Classify one InboundMessage against the patient's open doses.

    `msg` is a whatsapp.parser.InboundMessage (or anything with .text and
    .payload), `patient` a models.Patient, `open_doses` the list of that
    patient's non-terminal doses, each carrying `.id` and `.medicine_name`.
    """
    text = (getattr(msg, "text", None) or "").strip()
    payload = getattr(msg, "payload", None)
    forwarded = bool(getattr(msg, "forwarded", False))

    dose_id, ambiguous = resolve_dose(text, payload, open_doses)

    # A tapped option, where one still exists, is not open to interpretation.
    if payload:
        from app.whatsapp.client import DOSE_PAYLOAD_RE

        match = DOSE_PAYLOAD_RE.match(payload)
        if match:
            action = match.group(1)
            kind: IntentKind = {"TAKEN": "taken", "LATER": "later",
                                "SKIP": "not_taken"}[action]
            return Intent(kind=kind, dose_id=dose_id, reason=None,
                          confidence=1.0, text=text)

    if not text:
        return Intent(kind="unclear", dose_id=dose_id, reason=None,
                      confidence=0.0, text=text)

    fast = _fast_intent(text)
    if fast is not None:
        kind, confidence = fast
        if _not_an_answer(kind, forwarded):
            log.info("forwarded message read as %r - asking instead of recording it", kind)
            return Intent(kind="unclear", dose_id=dose_id, reason=text,
                          confidence=0.0, text=text, forwarded=True)
        if ambiguous and kind in ("taken", "later", "not_taken"):
            # We know WHAT they meant but not WHICH dose. Ask.
            return Intent(kind="unclear", dose_id=None, reason=text,
                          confidence=0.5, text=text)
        return Intent(kind=kind, dose_id=dose_id, reason=None,
                      confidence=confidence, text=text)

    try:
        data = await llm.chat_json(
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": text}],
            max_tokens=200,
        )
    except Exception as exc:  # noqa: BLE001 - a dead model must not lose a reply
        log.error("interpret failed, falling back to unclear: %s", exc)
        return Intent(kind="unclear", dose_id=dose_id, reason=text,
                      confidence=0.0, text=text)

    kind = str(data.get("kind", "unclear")).lower()
    if kind not in ("taken", "not_taken", "later", "question", "symptom",
                    "emergency", "unclear", "stop"):
        kind = "unclear"

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(max(confidence, 0.0), 1.0)

    medicine = data.get("medicine") or None
    reason = data.get("reason") or None

    # The keyword check is the authority on emergencies. A model deciding
    # "chest pain" is routine is a failure mode we do not accept.
    if guardrails.is_emergency(text):
        kind, confidence = "emergency", 1.0

    # If the model named a medicine, use it to break a tie.
    if ambiguous and medicine:
        picked = _medicine_in_text(medicine, open_doses)
        if picked:
            dose_id, ambiguous = picked, False

    if ambiguous and kind in ("taken", "later", "not_taken"):
        kind, confidence = "unclear", min(confidence, 0.5)

    if _not_an_answer(kind, forwarded):
        log.info("forwarded message read as %r - asking instead of recording it", kind)
        kind, confidence = "unclear", 0.0

    if confidence < CONFIDENCE_FLOOR and kind not in ("emergency", "stop"):
        log.info("confidence %.2f below floor for %r - treating as unclear",
                 confidence, text[:60])
        kind = "unclear"

    return Intent(kind=kind, dose_id=dose_id, reason=reason,
                  confidence=confidence, medicine=medicine, text=text,
                  forwarded=forwarded)
