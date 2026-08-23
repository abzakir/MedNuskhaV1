"""The caretaker talking to us on WhatsApp.

The patient side of this system is deliberately tiny - a reminder, a reply, an
acknowledgement. The caretaker side is different: they are the responsible
adult, they may be at work, and opening a dashboard to answer "did she take
it?" is friction. So they can ask here.

What they can do:
    status              today's doses for the patient
    pause / rok dein    stop reminders
    resume / shuru      start them again
    help                what can I ask

Deliberately NOT here: adding or editing a medicine. That needs the
confirmation screen (invariant 3), and a medicine created from a voice note
would bypass exactly the human check the whole design rests on.

Being the carer does not make the agent a doctor: a clinical question gets the
same refusal a patient would get (invariant 8).

Not in the AGENTS.md section 7 layout - added 2026-08-23 at the team's
request. Logged in PROJECT_LOG.md.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlmodel import col, select

from app.agent import guardrails, llm
from app.config import settings
from app.db import session_scope
from app.i18n import strings
from app.models import DoseEvent, Medicine, Patient, Schedule
from app.whatsapp import client as wa

log = logging.getLogger(__name__)

TAKEN_STATES = ("TAKEN", "TAKEN_LATE")
DECIDED_STATES = ("TAKEN", "TAKEN_LATE", "MISSED", "SKIPPED")

# --------------------------------------------------------------------------
# fast paths - a caretaker types the same four things over and over
# --------------------------------------------------------------------------

_STATUS_RE = re.compile(
    r"\b(status|report|update|kaisi?\s*hai|kaisa\s*hai|kya\s*haal|"
    r"kitni\s*li|li\s*ya\s*nahi|how\s*is|did\s*(she|he|they))\b|"
    r"رپورٹ|کیسی\s*ہے|کیسا\s*ہے",
    re.IGNORECASE,
)
_PAUSE_RE = re.compile(
    r"\b(pause|rok\s*(dein|do|den)|band\s*kar\s*(dein|do|den)|stop\s*reminders?|"
    r"mat\s*bhejo|na\s*bhejo)\b|روک\s*د|بند\s*کر",
    re.IGNORECASE,
)
_RESUME_RE = re.compile(
    r"\b(resume|shuru\s*(karein|karo|kar\s*dein)|start\s*(again|reminders?)|"
    r"chalu\s*kar|dobara\s*shuru)\b|شروع\s*کر|دوبارہ",
    re.IGNORECASE,
)
_HELP_RE = re.compile(
    r"\b(help|madad|kya\s*kar\s*sakta|commands?|options?|menu)\b|مدد",
    re.IGNORECASE,
)

_SYSTEM = """You classify one WhatsApp message from the CARETAKER of an elderly \
patient, sent to a medication reminder service. The message may be Urdu \
script, Roman Urdu, English, or a transcript of a voice note.

Choose exactly one kind:
- status: they want to know how the patient is doing, or whether a dose was taken
- pause: they want reminders stopped for now
- resume: they want reminders started again
- help: they are asking what they can do
- clinical: they are asking a medical question - whether to change a dose, \
what a symptom means, whether to stop a medicine
- other: anything else

Also extract "patient": the name they mention, or null.

Return ONLY JSON: {"kind": str, "patient": str|null, "confidence": float}
"""


#: Used only when the message fitted no command. The model may word the reply
#: back, but it still may not answer anything - it points at the four commands.
_UNCLEAR_SYSTEM = """You are MedNuskha, a medicine reminder service, replying to
the CARETAKER of an elderly patient. Their message did not match any command.

The only things you can do are: "status" (today's doses), "pause" (stop
reminders), "resume" (start them again), "help". Adding or editing a medicine
happens on the website, never here.

Hard rules:
- At most two short sentences.
- {register}
- Say you did not understand, then name the command that most likely fits what
  they asked. If nothing fits, tell them to send "help".
- Answer NOTHING medical - not what a medicine does, not whether to take,
  change or stop one, not what a symptom means.
- Invent no facts about the patient. You do not know how they are doing unless
  they ask for "status".
- No greeting, no sign-off, no emoji. Output the reply only."""

_REGISTER = {
    "ur": "Write in Roman Urdu (Urdu written in English letters), like: "
          "\"Maaf kijiye ga, samajh nahi aaya. 'status' likhein.\"",
    "en": "Write in plain English.",
}


async def _unclear_text(text: str, lang: str, patients: list[dict]) -> str | None:
    """Let the model word the 'did not understand' reply. None if it cannot.

    `care_unclear` is always ready behind this. The model chooses words, never
    actions - the command dispatch above has already decided nothing matched.
    """
    names = ", ".join(p["name"] for p in patients[:5]) or "none"
    register = _REGISTER.get(lang) or _REGISTER["ur"]

    draft = await llm.try_chat([
        {"role": "system", "content": _UNCLEAR_SYSTEM.format(register=register)},
        {"role": "user",
         "content": f"Patients in their care: {names}.\n"
                    f"They said: {(text or '').strip()[:200]!r}"},
    ])
    if draft is None:
        return None

    # Model prose reaching a human still gets checked, exactly as the patient
    # side does. A blocked draft falls back to the canned string.
    result = guardrails.check(draft)
    return None if result.alert_caretaker else result.message


def _fast_kind(text: str) -> str | None:
    clean = (text or "").strip()
    if not clean:
        return None
    # Clinical first: "should I stop her medicine" contains "stop", and
    # treating that as a pause command would be a quietly dangerous misread.
    if guardrails.asks_to_change_medication(clean):
        return "clinical"
    if _HELP_RE.search(clean):
        return "help"
    if _RESUME_RE.search(clean):
        return "resume"
    if _PAUSE_RE.search(clean):
        return "pause"
    if _STATUS_RE.search(clean):
        return "status"
    return None


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------


def patients_of(caretaker_id: str) -> list[dict]:
    with session_scope() as session:
        from app.models import Caretaker

        caretaker = session.get(Caretaker, caretaker_id)
        if caretaker is None:
            return []
        rows = session.exec(
            select(Patient).where(Patient.family_id == caretaker.family_id)
            .order_by(Patient.created_at)).all()
        return [{"id": p.id, "name": p.name, "stopped": p.stopped} for p in rows]


def _pick(patients: list[dict], text: str) -> dict | None:
    """Which patient the caretaker means. One patient needs no naming."""
    if not patients:
        return None
    if len(patients) == 1:
        return patients[0]
    lowered = (text or "").lower()
    for p in patients:
        if p["name"].lower() in lowered:
            return p
    return None


def _today_lines(patient_id: str, lang: str) -> tuple[int, int, str]:
    """(taken, total, one line per dose) for today, in local time."""
    now_local = datetime.now(settings.tz)
    start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    with session_scope() as session:
        rows = session.exec(
            select(DoseEvent, Medicine)
            .join(Schedule, Schedule.id == DoseEvent.schedule_id)
            .join(Medicine, Medicine.id == Schedule.medicine_id)
            .where(DoseEvent.patient_id == patient_id)
            .where(DoseEvent.scheduled_at >= start.astimezone(timezone.utc))
            .where(DoseEvent.scheduled_at < end.astimezone(timezone.utc))
            .order_by(DoseEvent.scheduled_at)).all()

    marks = {
        "TAKEN": "li", "TAKEN_LATE": "der se li", "MISSED": "NAHI LI",
        "SKIPPED": "chhori", "SCHEDULED": "abhi baaki", "SENT": "poocha hai",
        "AWAITING_REPLY": "jawab ka intezar", "REMINDED_AGAIN": "dobara poocha",
    } if lang == "ur" else {
        "TAKEN": "taken", "TAKEN_LATE": "taken late", "MISSED": "MISSED",
        "SKIPPED": "skipped", "SCHEDULED": "due", "SENT": "asked",
        "AWAITING_REPLY": "waiting", "REMINDED_AGAIN": "reminded again",
    }

    lines = []
    taken = 0
    for dose, medicine in rows:
        when = dose.scheduled_at
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        label = f"{medicine.name} {medicine.strength}".strip() if medicine.strength \
            else medicine.name
        lines.append(f"{when.astimezone(settings.tz):%H:%M}  {label} - "
                     f"{marks.get(dose.state, dose.state)}")
        if dose.state in TAKEN_STATES:
            taken += 1

    return taken, len(rows), "\n".join(lines)


def _set_stopped(patient_id: str, stopped: bool) -> None:
    with session_scope() as session:
        patient = session.get(Patient, patient_id)
        if patient is None:
            return
        patient.stopped = stopped
        if not stopped:
            patient.opted_in = True
            if patient.opted_in_at is None:
                patient.opted_in_at = datetime.now(timezone.utc)
        session.add(patient)
        session.commit()


# --------------------------------------------------------------------------
# the entry point
# --------------------------------------------------------------------------


async def handle(text: str, caretaker: dict) -> None:
    """Interpret one caretaker message and act on it.

    `caretaker` is {id, name, phone, language}. `text` is what they typed, or
    the transcript of their voice note - the two are treated identically.
    """
    lang = caretaker.get("language") or strings.DEFAULT_LANGUAGE
    phone = caretaker["phone"]

    async def say(key: str, **kwargs) -> None:
        await wa.send_text(phone, strings.t(key, lang, **kwargs))

    patients = await asyncio.to_thread(patients_of, caretaker["id"])
    if not patients:
        await say("care_no_patient")
        return

    kind = _fast_kind(text)
    named: str | None = None

    if kind is None:
        try:
            data = await llm.chat_json(
                [{"role": "system", "content": _SYSTEM},
                 {"role": "user", "content": text or ""}],
                max_tokens=150)
            kind = str(data.get("kind", "other")).lower()
            named = data.get("patient")
        except Exception as exc:  # noqa: BLE001 - a dead model must not lose it
            log.error("caretaker interpret failed: %s", exc)
            kind = "other"

    patient = _pick(patients, f"{text} {named or ''}")
    log.info("caretaker %s: kind=%s patient=%s",
             caretaker["id"], kind, patient["name"] if patient else None)

    if kind == "clinical":
        # Being the carer does not make the agent a doctor (invariant 8).
        await say("care_refusal", patient=patient["name"] if patient else "unhein")
        return

    if kind == "help":
        await say("care_help")
        return

    if kind in ("status", "pause", "resume") and patient is None:
        await say("care_which_patient",
                  names=", ".join(p["name"] for p in patients))
        return

    if kind == "status":
        taken, total, lines = await asyncio.to_thread(
            _today_lines, patient["id"], lang)
        if total == 0:
            await say("care_status_none", patient=patient["name"])
        else:
            await say("care_status", patient=patient["name"],
                      taken=taken, total=total, lines=lines)
        return

    if kind == "pause":
        await asyncio.to_thread(_set_stopped, patient["id"], True)
        await say("care_paused", patient=patient["name"])
        return

    if kind == "resume":
        await asyncio.to_thread(_set_stopped, patient["id"], False)
        try:
            from app.scheduler.ticker import materialise_doses
            await asyncio.to_thread(materialise_doses)
        except Exception as exc:  # noqa: BLE001 - the ticker will catch up
            log.warning("materialisation after resume failed: %s", exc)
        await say("care_resumed", patient=patient["name"])
        return

    # Nothing matched. Spend the key pool on a reply that at least points them
    # somewhere useful before falling back to the fixed one.
    worded = await _unclear_text(text, lang, patients)
    if worded:
        await wa.send_text(phone, worded)
        return
    await say("care_unclear")
