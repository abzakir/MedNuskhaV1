"""Medicine knowledge: AI-fetched draft in, caretaker-confirmed fact out.

Invariant 9 is the entire point of this module. A model's answer about a
medicine is a DRAFT. It is never shown to a patient and never usable by the
agent until a caretaker has read it and confirmed it on the dashboard.

At reply-time the agent may call `get_confirmed()` and nothing else. There is
deliberately no code path from a patient's question to a live model call about
what a medicine does - that is the one place in this system where a plausible
hallucination stops being a bug and becomes a patient-safety incident.

Signatures frozen in AGENTS.md section 9.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlmodel import select

from app.agent import llm
from app.db import session_scope
from app.models import MedicineReference

log = logging.getLogger(__name__)


@dataclass
class MedicineInfoDraft:
    """Structured medicine information, confirmed or not.

    Mirrors the medicine_reference table. `confirmed` is False for anything
    that came back from a model and has not been through a caretaker.
    """

    canonical_name: str
    purpose_ur: str | None = None
    purpose_en: str | None = None
    food_rule: str | None = None
    common_timing: str | None = None
    aliases: list[str] = field(default_factory=list)
    source: str = "ai_fetched"
    confirmed: bool = False

    def as_dict(self) -> dict:
        return {
            "canonical_name": self.canonical_name,
            "purpose_ur": self.purpose_ur,
            "purpose_en": self.purpose_en,
            "food_rule": self.food_rule,
            "common_timing": self.common_timing,
            "aliases": self.aliases,
            "source": self.source,
            "confirmed": self.confirmed,
        }


def normalise_name(name: str) -> str:
    """Lowercased and trimmed, so "Panadol " and "panadol" are one row."""
    return " ".join((name or "").strip().lower().split())


_FETCH_SYSTEM = """You are a pharmacology reference for a Pakistani medication \
reminder app. You are writing a DRAFT that a human caretaker will read and \
correct before it is ever shown to a patient.

Rules:
- Describe only what the medicine is commonly FOR. Never give a dose, never \
suggest starting or stopping anything, never diagnose.
- Write for someone with no medical training, in one short sentence per field.
- purpose_ur must be Roman Urdu (Latin letters), the way a Pakistani family \
writes on WhatsApp. Not Urdu script.
- If you do not recognise the medicine, set "known": false and leave the \
fields empty rather than guessing.

Return ONLY JSON with these keys:
{"known": bool, "canonical_name": str, "aliases": [str],
 "purpose_ur": str, "purpose_en": str, "food_rule": str, "common_timing": str}

food_rule example: "Khane ke baad lein" / "Khali pait lein"
common_timing example: "Subah aur raat"
"""


async def fetch_draft(name: str) -> MedicineInfoDraft:
    """Ask the model what this medicine is for. Returns a DRAFT.

    NEVER writes confirmed=true. NEVER called from the patient-facing reply
    path - a fetch happens only when a caretaker adds a medicine on the
    dashboard.

    A failed or unrecognised lookup returns an EMPTY draft rather than raising:
    the caretaker can always type the information in themselves, and a blank
    form is a better outcome than a blocked one.
    """
    clean = normalise_name(name)
    if not clean:
        return MedicineInfoDraft(canonical_name="")

    try:
        data = await llm.chat_json(
            [{"role": "system", "content": _FETCH_SYSTEM},
             {"role": "user", "content": f"Medicine name: {name}"}],
            max_tokens=400,
        )
    except Exception as exc:  # noqa: BLE001 - never block the caretaker
        log.warning("medicine lookup failed for %r: %s", name, exc)
        return MedicineInfoDraft(canonical_name=clean)

    if not data.get("known"):
        log.info("model did not recognise %r - returning a blank draft", name)
        return MedicineInfoDraft(canonical_name=clean)

    aliases = data.get("aliases") or []
    if not isinstance(aliases, list):
        aliases = []

    draft = MedicineInfoDraft(
        canonical_name=normalise_name(data.get("canonical_name") or clean),
        purpose_ur=(data.get("purpose_ur") or "").strip() or None,
        purpose_en=(data.get("purpose_en") or "").strip() or None,
        food_rule=(data.get("food_rule") or "").strip() or None,
        common_timing=(data.get("common_timing") or "").strip() or None,
        aliases=[str(a).strip() for a in aliases if str(a).strip()][:8],
        source="ai_fetched",
        confirmed=False,          # never anything else, from here
    )
    log.info("drafted medicine info for %r (unconfirmed)", draft.canonical_name)
    return draft


def get_confirmed(name: str) -> MedicineInfoDraft | None:
    """Read a confirmed medicine_reference row. DB read only, no model call.

    This is the ONLY function the agent may call at reply-time. Returns None
    when no confirmed row exists, and the agent must then say it does not know
    rather than invent an answer.
    """
    clean = normalise_name(name)
    if not clean:
        return None

    with session_scope() as session:
        row = session.exec(
            select(MedicineReference)
            .where(MedicineReference.canonical_name == clean)
            .where(MedicineReference.confirmed == True)      # noqa: E712
        ).first()

        if row is None:
            # A caretaker may have confirmed it under a brand name the patient
            # does not use, so check the alias lists too.
            for candidate in session.exec(
                select(MedicineReference)
                .where(MedicineReference.confirmed == True)  # noqa: E712
            ).all():
                if clean in {normalise_name(a) for a in (candidate.aliases or [])}:
                    row = candidate
                    break

        if row is None:
            log.info("no confirmed information for %r", clean)
            return None

        return MedicineInfoDraft(
            canonical_name=row.canonical_name,
            purpose_ur=row.purpose_ur,
            purpose_en=row.purpose_en,
            food_rule=row.food_rule,
            common_timing=row.common_timing,
            aliases=list(row.aliases or []),
            source=row.source,
            confirmed=True,
        )


def get_any(name: str) -> MedicineInfoDraft | None:
    """Read a row whether or not it is confirmed. For the DASHBOARD only.

    Lets the caretaker see an existing draft instead of paying for another
    lookup. Never call this from the reply path - that is what `get_confirmed`
    is for.
    """
    clean = normalise_name(name)
    if not clean:
        return None
    with session_scope() as session:
        row = session.exec(
            select(MedicineReference)
            .where(MedicineReference.canonical_name == clean)
        ).first()
        if row is None:
            return None
        return MedicineInfoDraft(
            canonical_name=row.canonical_name,
            purpose_ur=row.purpose_ur, purpose_en=row.purpose_en,
            food_rule=row.food_rule, common_timing=row.common_timing,
            aliases=list(row.aliases or []), source=row.source,
            confirmed=row.confirmed,
        )


async def save_confirmed(name: str, info: MedicineInfoDraft,
                         caretaker_id: str) -> str:
    """Write the row with confirmed=true. Returns its id.

    Called ONLY from the dashboard's confirm action. `caretaker_id` is stored
    so a report can always say which human signed off on the wording.
    """
    clean = normalise_name(info.canonical_name or name)
    if not clean:
        raise ValueError("cannot confirm a medicine with no name")

    now = datetime.now(timezone.utc)

    with session_scope() as session:
        row = session.exec(
            select(MedicineReference)
            .where(MedicineReference.canonical_name == clean)
        ).first()

        if row is None:
            row = MedicineReference(canonical_name=clean, fetched_at=now)

        row.purpose_ur = info.purpose_ur
        row.purpose_en = info.purpose_en
        row.food_rule = info.food_rule
        row.common_timing = info.common_timing
        row.aliases = list(info.aliases or [])
        # A caretaker who edited the text owns it now, not the model.
        row.source = "caretaker_edited" if info.source != "ai_fetched" else info.source
        row.confirmed = True
        row.confirmed_by = caretaker_id
        row.confirmed_at = now

        session.add(row)
        session.commit()
        session.refresh(row)
        log.info("medicine %r confirmed by caretaker %s", clean, caretaker_id)
        return row.id
