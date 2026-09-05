"""Act on an Intent, and send the one short warm reply.

Style rules (AGENTS.md section 11): one idea per message, the reader is 68 and
reading slowly. Name the medicine and its strength every time. Never scold - a
missed dose gets warmth and a second chance. Reply in whatever language the
patient used.

Every outbound message passes through guardrails.check() before it is sent,
with no exceptions. For a patient's question the ONLY knowledge source is
knowledge.get_confirmed(); if that returns None the agent says so and offers to
ask the caretaker. It never falls back to asking a model (invariant 9).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlmodel import col, select

from app.agent import guardrails, knowledge, llm
from app.agent.interpret import Intent
from app.config import settings
from app.db import session_scope
from app.i18n import strings
from app.models import (Caretaker, DoseEvent, Medicine, MedicineReference,
                        Patient, Schedule, SymptomReport)
from app.scheduler import state_machine as sm
from app.whatsapp import client as wa

log = logging.getLogger(__name__)

#: States in which a dose can still receive a reply.
OPEN_STATES = ("SENT", "AWAITING_REPLY", "REMINDED_AGAIN")


class OpenDose:
    """A dose awaiting an answer, with the bits the agent needs."""

    __slots__ = ("id", "medicine_name", "medicine_label", "state", "scheduled_at")

    def __init__(self, id, medicine_name, medicine_label, state, scheduled_at):
        self.id = id
        self.medicine_name = medicine_name
        self.medicine_label = medicine_label
        self.state = state
        self.scheduled_at = scheduled_at

    def __repr__(self) -> str:
        return f"<OpenDose {self.medicine_label} {self.state}>"


# --------------------------------------------------------------------------
# context
# --------------------------------------------------------------------------


#: How far back a MISSED dose can still be confirmed late. Beyond this the
#: patient is talking about something else, and a stale dose from three days
#: ago should not be pulled into the conversation.
LATE_CONFIRMATION_WINDOW = timedelta(hours=12)


def open_doses_for(patient_id: str, include_missed: bool = True) -> list[OpenDose]:
    """Doses this patient could plausibly be replying about.

    Recently MISSED doses are included so a late confirmation still lands
    (section 4.8) - that is what turns MISSED into TAKEN_LATE - but only
    recent ones. Missed doses accumulate, and an unbounded list of them made
    every reply look ambiguous.
    """
    states = list(OPEN_STATES) + (["MISSED"] if include_missed else [])
    cutoff = datetime.now(timezone.utc) - LATE_CONFIRMATION_WINDOW
    out: list[OpenDose] = []
    with session_scope() as session:
        rows = session.exec(
            select(DoseEvent, Medicine)
            .join(Schedule, Schedule.id == DoseEvent.schedule_id)
            .join(Medicine, Medicine.id == Schedule.medicine_id)
            .where(DoseEvent.patient_id == patient_id)
            .where(col(DoseEvent.state).in_(states))
            .where(DoseEvent.scheduled_at >= cutoff)
            .order_by(DoseEvent.scheduled_at.desc())
            .limit(10)
        ).all()
        for dose, medicine in rows:
            label = medicine.name
            if medicine.strength:
                label = f"{medicine.name} {medicine.strength}"
            out.append(OpenDose(dose.id, medicine.name, label,
                                dose.state, dose.scheduled_at))
    return out


def _caretakers_for(patient_id: str) -> list[dict]:
    with session_scope() as session:
        patient = session.get(Patient, patient_id)
        if patient is None:
            return []
        rows = session.exec(
            select(Caretaker).where(Caretaker.family_id == patient.family_id)).all()
        return [{"id": c.id, "name": c.name, "phone": c.phone,
                 "relation": c.relation, "language": c.language} for c in rows]


def _known_texts(patient_id: str) -> list[str]:
    """Everything a caretaker has already approved for this patient.

    Two guardrails read it. Invariant 10 checks dose figures against it, so
    "Panadol 500mg" passes and an invented "take 1000mg" does not; the
    foreign-medicine check reads the same list to tell this patient's
    medicines from somebody else's.

    The CONFIRMED reference text is in here too, and has to be: `_on_question`
    quotes it back verbatim, and a caretaker-approved sentence that happens to
    mention another brand - "Panadol ka generic hai" - would otherwise trip
    the foreign-medicine check and turn an answer into a refusal. Invariant 9
    already says a confirmed row is the one thing the agent may repeat, so
    anything in it is by definition allowed out again.
    """
    with session_scope() as session:
        rows = session.exec(
            select(Medicine).where(Medicine.patient_id == patient_id)).all()
        texts: list[str] = []
        for m in rows:
            texts.append(f"{m.name} {m.strength or ''}")
            if m.notes:
                texts.append(m.notes)
            if not m.reference_id:
                continue
            ref = session.get(MedicineReference, m.reference_id)
            if ref is None or not ref.confirmed:
                continue          # invariant 9: a draft is not approved text
            texts.extend(t for t in (ref.canonical_name, ref.purpose_ur,
                                     ref.purpose_en, ref.food_rule,
                                     ref.common_timing) if t)
            texts.extend(ref.aliases or [])
        return texts


#: (names, expires_at) for `_all_medicine_names`. Two whole-table reads on
#: every outbound message is a query per sentence for a list that changes when
#: somebody adds a medicine - minutes apart at best, never mid-conversation.
_MEDICINE_NAMES: tuple[list[str], float] = ([], 0.0)
_MEDICINE_NAMES_TTL = 60.0


def _all_medicine_names() -> list[str]:
    """Every medicine name the system has ever been told about.

    Passed to the guardrail so it can tell a medicine this patient is NOT on
    from an ordinary word. The seed list in guardrails covers the pharmacy
    shelf a model reaches for unprompted; this covers everything anyone here
    has actually prescribed, and grows on its own.

    Cached for a minute. A medicine added on the dashboard is in the list
    before the patient could answer anything about it, and a stale entry only
    ever means the guardrail is briefly *less* suspicious of a name - never
    that it blocks one it should not.
    """
    global _MEDICINE_NAMES
    names, expires = _MEDICINE_NAMES
    if time.monotonic() < expires:
        return names

    try:
        with session_scope() as session:
            names = [m.name for m in session.exec(select(Medicine)).all()]
            for ref in session.exec(select(MedicineReference)).all():
                names.append(ref.canonical_name)
                names.extend(ref.aliases or [])
        names = [n for n in names if n]
    except Exception as exc:  # noqa: BLE001 - the seed list still guards us
        log.warning("could not read the medicine corpus (%s) - the guardrail "
                    "falls back to its seed list", exc)
        return names

    _MEDICINE_NAMES = (names, time.monotonic() + _MEDICINE_NAMES_TTL)
    return names


# --------------------------------------------------------------------------
# sending
# --------------------------------------------------------------------------


async def _send_checked(patient, draft: str, *, intent: Intent | None = None,
                        caretakers: list[dict] | None = None,
                        known_texts: list[str] | None = None) -> None:
    """Guardrail, then send. The only way this module talks to a patient."""
    caretakers = caretakers if caretakers is not None else _caretakers_for(patient.id)
    primary = caretakers[0]["name"] if caretakers else "aap ke ghar walon"

    # The guardrail needs to know which medicines exist at all, so it can
    # tell one this patient is not on from an ordinary word.
    known_medicines = await asyncio.to_thread(_all_medicine_names)
    result = guardrails.check(draft, patient=patient, intent=intent,
                              known_texts=known_texts, caretaker_name=primary,
                              known_medicines=known_medicines)

    await wa.send_text(patient.whatsapp_number, result.message)

    if result.alert_caretaker:
        await _alert_caretakers(
            caretakers,
            reason=result.violated_rule or "guardrail",
            patient=patient,
            words=(intent.text if intent else None) or "",
        )


async def _speak_back(patient, intent, key: str, **values) -> bool:
    """Answer a voice note with a voice note. Phase 5.

    Reply in the modality they used: someone who sends a voice message is
    often someone who finds reading hard, and a text-only answer is the wrong
    shape of reply for them. Someone who typed gets text, because a surprise
    audio clip is noise.

    Only `strings.SPOKEN` templates are ever spoken, filled with values this
    module controls. Nothing free-text from the database goes through here -
    the voice silently drops Roman Urdu words, and a reply that loses one is
    worse than a reply they have to read. See strings.SPOKEN for the measurement.
    """
    if not settings.voice_notes_enabled:
        return False
    if not getattr(intent, "from_voice", False):
        return False

    line = strings.spoken(key, **values)
    if not line:
        return False

    try:
        from app.voice import store, tts

        # `values` carries the medicine when the line names one, so the
        # same swallowed-name check covers the spoken reply too.
        cached = await tts.ensure_spoken(line, values.get("medicine"))
        if cached is None:
            return False
        audio = await asyncio.to_thread(store.get, cached)
        if not audio:
            return False
        await wa.send_voice(patient.whatsapp_number, audio)
        return True
    except Exception as exc:  # noqa: BLE001 - they already have the text
        log.warning("spoken reply not sent to %s: %s", patient.id, exc)
        return False


async def _alert_caretakers(caretakers: list[dict], *, reason: str,
                            patient, words: str) -> None:
    """Tell the caretakers something needs a human.

    A caretaker who signed up with an email and has not yet added their
    WhatsApp number is skipped rather than attempted: `caretaker.phone` is
    nullable, and sending to it raises inside the loop and buries a real
    alert under a stack trace. The dashboard already nags them for it.
    """
    reachable = [c for c in caretakers if c.get("phone")]
    if caretakers and not reachable:
        log.warning("patient %s needs a human (%s) but no caretaker in the "
                    "family has a WhatsApp number", patient.id, reason)

    for caretaker in reachable:
        lang = caretaker.get("language") or "ur"
        body = strings.t("caretaker_emergency", lang,
                         patient=patient.name, words=(words or "")[:200])
        try:
            await wa.send_text(caretaker["phone"], body)
        except Exception as exc:  # noqa: BLE001 - try the next caretaker
            log.error("could not alert caretaker %s: %s", caretaker["phone"], exc)


# --------------------------------------------------------------------------
# the entry point
# --------------------------------------------------------------------------


async def respond(intent: Intent, patient) -> None:
    """Handle one Intent end to end: transition the dose, reply, alert."""
    lang = patient.language or strings.DEFAULT_LANGUAGE
    caretakers = await asyncio.to_thread(_caretakers_for, patient.id)
    primary = caretakers[0]["name"] if caretakers else "aap ke ghar walon"
    known = await asyncio.to_thread(_known_texts, patient.id)

    log.info("patient %s intent=%s dose=%s confidence=%.2f",
             patient.id, intent.kind, intent.dose_id, intent.confidence)

    # An emergency outranks everything, including the opt-in gate below: a
    # patient writing "chest pain" gets the emergency copy whether or not they
    # have ever agreed to reminders (section 11).
    if intent.kind == "emergency":
        await _on_emergency(intent, patient, lang, caretakers, primary, known)
        return

    # Section 4.4: a patient who has not opted in has been asked exactly one
    # question - whether to start at all - and their reply is the answer to
    # that, not a dose confirmation. They have no doses either, because
    # materialisation skips them, so the ordinary path can only ever answer
    # "samajh nahi aaya" and the patient is stranded with reminders off
    # forever. This is the only way back in.
    if not patient.opted_in and not patient.stopped:
        await _on_optin(intent, patient, lang, caretakers, primary, known)
        return

    handler = {
        "taken": _on_taken,
        "later": _on_later,
        "not_taken": _on_not_taken,
        "question": _on_question,
        "symptom": _on_symptom,
        "stop": _on_stop,
        "unclear": _on_unclear,
    }.get(intent.kind, _on_unclear)

    await handler(intent, patient, lang, caretakers, primary, known)


async def _on_optin(intent, patient, lang, caretakers, primary, known) -> None:
    """The reply to `patient_optin` - the one question a new handset is asked.

    "HAAN" is what the intro message asks for, and until it arrives nothing is
    sent to that number. A refusal is honoured as a STOP; anything else is met
    with the intro message again, because there is only one thing to say.
    """
    if intent.kind == "stop":
        await _on_stop(intent, patient, lang, caretakers, primary, known)
        return

    from app.agent.interpret import is_affirmative

    if intent.kind == "taken" or is_affirmative(intent.text or ""):
        await asyncio.to_thread(_set_opted_in, patient.id)
        patient.opted_in = True
        log.info("patient %s opted in", patient.id)

        # Their doses were never materialised while they were opted out, so
        # the first reminder would otherwise wait for a schedule day to turn
        # over rather than arriving at the next dose time.
        try:
            from app.scheduler.ticker import materialise_doses
            await asyncio.to_thread(materialise_doses)
        except Exception as exc:  # noqa: BLE001 - the ticker will catch up
            log.warning("materialisation after opt-in failed: %s", exc)

        body = strings.t("optin_confirmed", lang, name=patient.name)
        # No SPOKEN template for this one: the intro and its answer are a
        # written exchange, and strings.SPOKEN is the whole of what may be
        # spoken aloud.
        await _send_checked(patient, body, intent=intent, caretakers=caretakers,
                            known_texts=known)
        return

    log.info("patient %s has not opted in yet and did not say HAAN - "
             "re-sending the intro", patient.id)
    body = strings.t("patient_optin", lang, name=patient.name, caretaker=primary)
    await _send_checked(patient, body, intent=intent, caretakers=caretakers,
                        known_texts=known)


async def _on_emergency(intent, patient, lang, caretakers, primary, known) -> None:
    """Fixed copy only. The model never improvises on a chest-pain message."""
    result = guardrails.emergency_response(patient, primary)
    await wa.send_text(patient.whatsapp_number, result.message)
    await _alert_caretakers(caretakers, reason="emergency", patient=patient,
                            words=intent.text or "")
    await asyncio.to_thread(_record_symptom, patient.id, intent, "emergency", True)


async def _nothing_pending(intent, patient, lang, caretakers, known) -> bool:
    """Answer honestly when they spoke about a dose and there is none.

    Understanding somebody and having nothing to record are different things,
    and "samajh nahi aaya" says the first when only the second is true. A
    patient whose course has finished can then say "mene dawai kha li hai" in
    Urdu, in English, by voice and by text, and be told every single time that
    she was not understood - there is no sentence she could have sent that
    would have worked. Observed on a real phone 2026-09-06, after a one-day
    Panadol course had already completed.

    Returns True when it has answered and the caller should stop.
    """
    if await asyncio.to_thread(open_doses_for, patient.id):
        return False
    log.info("dose answer with nothing open for patient %s - saying so",
             patient.id)
    body = strings.t("no_dose_pending", lang, name=patient.name)
    await _send_checked(patient, body, intent=intent, caretakers=caretakers,
                        known_texts=known)
    return True


async def _on_taken(intent, patient, lang, caretakers, primary, known) -> None:
    if not intent.dose_id:
        if await _nothing_pending(intent, patient, lang, caretakers, known):
            return
        await _on_unclear(intent, patient, lang, caretakers, primary, known)
        return

    landed = await asyncio.to_thread(
        sm.confirm_taken, intent.dose_id, _source(intent), intent.text)

    label = await asyncio.to_thread(_label_for, intent.dose_id)
    key = "dose_late_ack" if landed == "TAKEN_LATE" else "dose_taken_ack"
    body = strings.t(key, lang, name=patient.name, medicine=label)
    await _send_checked(patient, body, intent=intent, caretakers=caretakers,
                        known_texts=known)
    await _speak_back(patient, intent, key, medicine=label)

    if landed == "TAKEN_LATE":
        from app.scheduler.ticker import notify_late_resolution
        await notify_late_resolution(intent.dose_id)


async def _on_later(intent, patient, lang, caretakers, primary, known) -> None:
    """"Abhi nahi" is acknowledged but is NOT a snooze - the dose stays open so
    the follow-up and escalation still run (section 4)."""
    if intent.dose_id:
        await asyncio.to_thread(_record_reason, intent.dose_id,
                                intent.text or "abhi nahi")
    elif await _nothing_pending(intent, patient, lang, caretakers, known):
        # Promising to remind her again when the course is over and reminders
        # are stopped is a plain untruth, and it is what made the next four
        # replies look like a comprehension failure rather than an empty
        # schedule.
        return
    body = strings.t("dose_later_ack", lang, name=patient.name)
    await _send_checked(patient, body, intent=intent, caretakers=caretakers,
                        known_texts=known)


async def _on_not_taken(intent, patient, lang, caretakers, primary, known) -> None:
    """They said no and gave a reason. Record it verbatim for the doctor."""
    if intent.dose_id:
        await asyncio.to_thread(sm.mark_skipped, intent.dose_id,
                                intent.reason or intent.text, _source(intent))
    elif await _nothing_pending(intent, patient, lang, caretakers, known):
        return
    body = strings.t("dose_later_ack", lang, name=patient.name)
    await _send_checked(patient, body, intent=intent, caretakers=caretakers,
                        known_texts=known)
    await _alert_caretakers(caretakers, reason="not_taken", patient=patient,
                            words=intent.reason or intent.text or "")


async def _on_question(intent, patient, lang, caretakers, primary, known) -> None:
    """INVARIANT 9 lives here.

    The only knowledge source is a caretaker-confirmed row. If there is none,
    the agent says it does not know. It never asks a model what a medicine is
    for, and never repeats an unconfirmed draft.
    """
    # "Can I take Panadol twice?" is not a request for information, it is a
    # request to change a dose. Answering it at all - even with "I don't know"
    # - is the wrong shape of reply. Section 11 wants the refusal and a human.
    if guardrails.asks_to_change_medication(intent.text or ""):
        log.info("patient asked to change a dose - refusing (section 11)")
        body = strings.t("refusal_clinical", lang, caretaker=primary)
        await wa.send_text(patient.whatsapp_number, body)
        await _alert_caretakers(caretakers, reason="dose_change_request",
                                patient=patient, words=intent.text or "")
        return

    name = intent.medicine
    if not name:
        doses = await asyncio.to_thread(open_doses_for, patient.id)
        name = doses[0].medicine_name if doses else None

    info = await asyncio.to_thread(knowledge.get_confirmed, name) if name else None

    if info is None:
        body = strings.t("medicine_info_unconfirmed", lang, caretaker=primary)
        await _send_checked(patient, body, intent=intent, caretakers=caretakers,
                            known_texts=known)
        await _alert_caretakers(
            caretakers, reason="unconfirmed_medicine_question", patient=patient,
            words=intent.text or "")
        return

    purpose = (info.purpose_ur if lang == "ur" else info.purpose_en) \
        or info.purpose_en or info.purpose_ur or ""
    body = strings.t("medicine_info", lang,
                     medicine=info.canonical_name.title(),
                     # The template supplies the full stop; a
                     # caretaker-confirmed sentence usually ends with
                     # one of its own, and the pair read as
                     # "...hoti hai.. Khane ke baad lein" on a phone.
                     purpose=_unpunctuated(purpose),
                     food_rule=info.food_rule or "")
    await _send_checked(patient, " ".join(body.split()), intent=intent,
                        caretakers=caretakers, known_texts=known)


def _unpunctuated(text: str) -> str:
    """Trim a trailing sentence stop so the template can add its own."""
    return (text or "").strip().rstrip("۔.").strip()


async def _on_symptom(intent, patient, lang, caretakers, primary, known) -> None:
    """Record verbatim, never interpret (invariant 8)."""
    await asyncio.to_thread(_record_symptom, patient.id, intent, "routine", True)
    body = strings.t("symptom_ack", lang, caretaker=primary)
    await _send_checked(patient, body, intent=intent, caretakers=caretakers,
                        known_texts=known)
    await _alert_caretakers(caretakers, reason="symptom", patient=patient,
                            words=intent.text or "")


async def _on_stop(intent, patient, lang, caretakers, primary, known) -> None:
    await asyncio.to_thread(_set_stopped, patient.id)
    body = strings.t("stopped", lang, name=patient.name, caretaker=primary)
    await wa.send_text(patient.whatsapp_number, body)
    await _alert_caretakers(caretakers, reason="stop", patient=patient,
                            words=intent.text or "")


#: Asking again is the one place the agent may word its own sentence. It is
#: still only allowed to ask which dose - never to inform, advise or decide.
_CLARIFY_SYSTEM = """You are MedNuskha, a medicine reminder for an elderly patient.
You did NOT understand their last message. Write ONE short question asking them
to say it again.

Hard rules:
- ONE sentence, at most 20 words. They are 68 and reading slowly.
- {register}
- Warm, never scolding. Not understanding is your fault, not theirs.
- If a medicine is named below, ask whether they have taken THAT medicine.
- Say NOTHING about what any medicine does, whether to take it, dosage,
  timing, or health. You are asking a question, not giving information.
- No greeting, no sign-off, no emoji. Output the sentence only."""

#: The worked example must NOT name a real medicine. It used to say
#: "...kya aap ne Panadol le li hai?", and on 2026-08-30 the model copied
#: that example verbatim instead of substituting the patient's own
#: medicine - asking a woman taking polymalt whether she had taken
#: Panadol. A medication reminder naming a drug the patient is not on is
#: the worst thing this file can do, so there is now no drug name left in
#: the prompt for a model to reach for.
_REGISTER = {
    "ur": "Write in Roman Urdu (Urdu written in English letters), like: "
          "\"Maaf kijiye ga, samajh nahi aaya. Kya aap ne apni dawai le "
          "li hai?\" - but replace \"apni dawai\" with the medicine "
          "named below whenever one is given.",
    "en": "Write in plain English, like: "
          "\"Sorry, I didn't catch that. Have you taken your medicine?\""
          " - but replace \"your medicine\" with the medicine named "
          "below whenever one is given.",
}


async def _clarify_text(intent, lang: str, doses: list) -> str | None:
    """Let the model word the 'say that again' question. None if it cannot.

    The canned string is always ready behind this - the model is spent on
    wording, never on deciding anything. Whatever comes back still goes
    through guardrails like every other draft.
    """
    if doses:
        names = ", ".join(d.medicine_label for d in doses[:3])
        context = f"Medicine(s) awaiting an answer: {names}."
    else:
        context = "No dose is awaiting an answer right now."

    register = _REGISTER.get(lang) or _REGISTER["ur"]
    said = (intent.text or "").strip()[:200]

    worded = await llm.try_chat([
        {"role": "system", "content": _CLARIFY_SYSTEM.format(register=register)},
        {"role": "user", "content": f"{context}\nThey said: {said!r}"},
    ])
    if worded is None:
        return None

    # If we handed the model a medicine to ask about, its sentence has to
    # be about THAT medicine. One naming none of them is either generic -
    # where the canned string says it better anyway - or it has named
    # something we never mentioned, which is how a patient taking polymalt
    # was asked about Panadol. Either way the canned string is the answer.
    if doses and not _names_one_of(worded, doses):
        log.warning(
            "the clarifying question named no medicine we offered it "
            "(%r) - using the canned string instead", worded[:120])
        return None

    return worded


def _names_one_of(text: str, doses: list) -> bool:
    """True when `text` mentions the medicine of one of these doses.

    Matched on the medicine's own name words rather than the whole label,
    so "Panadol" still counts when the label is "Panadol 500mg".
    """
    lowered = (text or "").lower()
    for dose in doses:
        for word in (getattr(dose, "medicine_name", "") or "").lower().split():
            if len(word) >= 4 and word in lowered:
                return True
    return False


async def _on_unclear(intent, patient, lang, caretakers, primary, known) -> None:
    """Ask ONE short question. Never guess (section 11)."""
    # An unclear message that is nevertheless clearly about changing a dose
    # gets the refusal rather than a clarifying question.
    if guardrails.asks_to_change_medication(intent.text or ""):
        body = strings.t("refusal_clinical", lang, caretaker=primary)
        await wa.send_text(patient.whatsapp_number, body)
        await _alert_caretakers(caretakers, reason="dose_change_request",
                                patient=patient, words=intent.text or "")
        return

    # The SAME view of "open" that interpret was given. It used to exclude
    # MISSED here, and interpret includes them - so once a dose had escalated,
    # interpret could see two missed medicines, call the reply ambiguous, and
    # hand over to a branch that then saw no doses at all and could not name
    # what it was asking about. A patient answering "le li hai" by voice and
    # then by text got "samajh nahi aaya" every time, because nothing changed
    # between attempts. Observed on a real phone 2026-09-05.
    doses = await asyncio.to_thread(open_doses_for, patient.id)

    # We understood them, we just do not know which medicine. Say THAT, and
    # name every option, rather than claiming not to have understood and then
    # asking about one of them at random. A patient who says "yes I have taken
    # this" and is told "sorry, I didn't catch that" says it again, and it
    # happens again - three times in ninety seconds, on a real phone.
    if getattr(intent, "ambiguous", False):
        from app.agent.interpret import distinct_medicines

        options = distinct_medicines(doses)
        if len(options) > 1:
            body = strings.t("which_medicine", lang, name=patient.name,
                             medicines=" ya ".join(options) if lang == "ur"
                             else " or ".join(options))
            await _send_checked(patient, body, intent=intent,
                                caretakers=caretakers, known_texts=known)
            return

    # Spend the key pool on a better-worded question before settling for the
    # canned one - "samajh nahi aaya" every time reads like a broken machine.
    body = await _clarify_text(intent, lang, doses)

    if body is None:
        if len(doses) == 1:
            body = strings.t("clarify", lang, medicine=doses[0].medicine_label)
        elif len(doses) > 1:
            names = " ya ".join(d.medicine_label for d in doses[:3])
            body = strings.t("clarify", lang, medicine=names)
        else:
            body = strings.t("clarify_generic", lang)

    await _send_checked(patient, body, intent=intent, caretakers=caretakers,
                        known_texts=known)


# --------------------------------------------------------------------------
# small DB helpers
# --------------------------------------------------------------------------


def _source(intent: Intent) -> str:
    return "voice" if getattr(intent, "from_voice", False) else "text"


def _label_for(dose_id: str) -> str:
    with session_scope() as session:
        dose = session.get(DoseEvent, dose_id)
        if dose is None:
            return "dawai"
        schedule = session.get(Schedule, dose.schedule_id)
        medicine = session.get(Medicine, schedule.medicine_id) if schedule else None
        if medicine is None:
            return "dawai"
        return f"{medicine.name} {medicine.strength}".strip() if medicine.strength \
            else medicine.name


def _record_reason(dose_id: str, text: str) -> None:
    """Store the patient's words without touching `state` - section 8 reserves
    transitions for state_machine.py."""
    with session_scope() as session:
        dose = session.get(DoseEvent, dose_id)
        if dose is None:
            return
        dose.response_text = text
        dose.reason = text
        session.add(dose)
        session.commit()


def _record_symptom(patient_id: str, intent: Intent, severity: str,
                    alerted: bool) -> None:
    with session_scope() as session:
        session.add(SymptomReport(
            patient_id=patient_id,
            dose_event_id=intent.dose_id,
            # Verbatim. The doctor report quotes this exactly (section 6).
            text_verbatim=(intent.text or "")[:2000],
            severity=severity,
            caretaker_alerted=alerted,
            reported_at=datetime.now(timezone.utc),
        ))
        session.commit()


def _set_opted_in(patient_id: str) -> None:
    with session_scope() as session:
        patient = session.get(Patient, patient_id)
        if patient is None:
            return
        patient.opted_in = True
        patient.stopped = False
        if patient.opted_in_at is None:
            patient.opted_in_at = datetime.now(timezone.utc)
        session.add(patient)
        session.commit()


def _set_stopped(patient_id: str) -> None:
    with session_scope() as session:
        patient = session.get(Patient, patient_id)
        if patient is None:
            return
        patient.stopped = True
        session.add(patient)
        session.commit()
    log.warning("patient %s sent STOP - all reminders halted", patient_id)
