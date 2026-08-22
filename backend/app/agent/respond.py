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
from datetime import datetime, timezone

from sqlmodel import col, select

from app.agent import guardrails, knowledge
from app.agent.interpret import Intent
from app.db import session_scope
from app.i18n import strings
from app.models import (Caretaker, DoseEvent, Medicine, Patient, Schedule,
                        SymptomReport)
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


def open_doses_for(patient_id: str, include_missed: bool = True) -> list[OpenDose]:
    """Doses this patient could plausibly be replying about.

    Recently MISSED doses are included so a late confirmation still lands
    (section 4.8) - that is what turns MISSED into TAKEN_LATE.
    """
    states = list(OPEN_STATES) + (["MISSED"] if include_missed else [])
    out: list[OpenDose] = []
    with session_scope() as session:
        rows = session.exec(
            select(DoseEvent, Medicine)
            .join(Schedule, Schedule.id == DoseEvent.schedule_id)
            .join(Medicine, Medicine.id == Schedule.medicine_id)
            .where(DoseEvent.patient_id == patient_id)
            .where(col(DoseEvent.state).in_(states))
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
    """Every dose figure the database actually holds for this patient.

    Invariant 10 checks outbound text against this, so "Panadol 500mg" passes
    and an invented "take 1000mg" does not.
    """
    with session_scope() as session:
        rows = session.exec(
            select(Medicine).where(Medicine.patient_id == patient_id)).all()
        texts: list[str] = []
        for m in rows:
            texts.append(f"{m.name} {m.strength or ''}")
            if m.notes:
                texts.append(m.notes)
        return texts


# --------------------------------------------------------------------------
# sending
# --------------------------------------------------------------------------


async def _send_checked(patient, draft: str, *, intent: Intent | None = None,
                        caretakers: list[dict] | None = None,
                        known_texts: list[str] | None = None) -> None:
    """Guardrail, then send. The only way this module talks to a patient."""
    caretakers = caretakers if caretakers is not None else _caretakers_for(patient.id)
    primary = caretakers[0]["name"] if caretakers else "aap ke ghar walon"

    result = guardrails.check(draft, patient=patient, intent=intent,
                              known_texts=known_texts, caretaker_name=primary)

    await wa.send_text(patient.whatsapp_number, result.message)

    if result.alert_caretaker:
        await _alert_caretakers(
            caretakers,
            reason=result.violated_rule or "guardrail",
            patient=patient,
            words=(intent.text if intent else None) or "",
        )


async def _alert_caretakers(caretakers: list[dict], *, reason: str,
                            patient, words: str) -> None:
    """Tell the caretakers something needs a human."""
    for caretaker in caretakers:
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

    handler = {
        "emergency": _on_emergency,
        "taken": _on_taken,
        "later": _on_later,
        "not_taken": _on_not_taken,
        "question": _on_question,
        "symptom": _on_symptom,
        "stop": _on_stop,
        "unclear": _on_unclear,
    }.get(intent.kind, _on_unclear)

    await handler(intent, patient, lang, caretakers, primary, known)


async def _on_emergency(intent, patient, lang, caretakers, primary, known) -> None:
    """Fixed copy only. The model never improvises on a chest-pain message."""
    result = guardrails.emergency_response(patient, primary)
    await wa.send_text(patient.whatsapp_number, result.message)
    await _alert_caretakers(caretakers, reason="emergency", patient=patient,
                            words=intent.text or "")
    await asyncio.to_thread(_record_symptom, patient.id, intent, "emergency", True)


async def _on_taken(intent, patient, lang, caretakers, primary, known) -> None:
    if not intent.dose_id:
        await _on_unclear(intent, patient, lang, caretakers, primary, known)
        return

    landed = await asyncio.to_thread(
        sm.confirm_taken, intent.dose_id, _source(intent), intent.text)

    label = await asyncio.to_thread(_label_for, intent.dose_id)
    key = "dose_late_ack" if landed == "TAKEN_LATE" else "dose_taken_ack"
    body = strings.t(key, lang, name=patient.name, medicine=label)
    await _send_checked(patient, body, intent=intent, caretakers=caretakers,
                        known_texts=known)

    if landed == "TAKEN_LATE":
        from app.scheduler.ticker import notify_late_resolution
        await notify_late_resolution(intent.dose_id)


async def _on_later(intent, patient, lang, caretakers, primary, known) -> None:
    """"Abhi nahi" is acknowledged but is NOT a snooze - the dose stays open so
    the follow-up and escalation still run (section 4)."""
    if intent.dose_id:
        await asyncio.to_thread(_record_reason, intent.dose_id,
                                intent.text or "abhi nahi")
    body = strings.t("dose_later_ack", lang, name=patient.name)
    await _send_checked(patient, body, intent=intent, caretakers=caretakers,
                        known_texts=known)


async def _on_not_taken(intent, patient, lang, caretakers, primary, known) -> None:
    """They said no and gave a reason. Record it verbatim for the doctor."""
    if intent.dose_id:
        await asyncio.to_thread(sm.mark_skipped, intent.dose_id,
                                intent.reason or intent.text, _source(intent))
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
                     purpose=purpose,
                     food_rule=info.food_rule or "")
    await _send_checked(patient, " ".join(body.split()), intent=intent,
                        caretakers=caretakers, known_texts=known)


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


async def _on_unclear(intent, patient, lang, caretakers, primary, known) -> None:
    """Ask ONE short question. Never guess (section 11)."""
    doses = await asyncio.to_thread(open_doses_for, patient.id, False)

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


def _set_stopped(patient_id: str) -> None:
    with session_scope() as session:
        patient = session.get(Patient, patient_id)
        if patient is None:
            return
        patient.stopped = True
        session.add(patient)
        session.commit()
    log.warning("patient %s sent STOP - all reminders halted", patient_id)
