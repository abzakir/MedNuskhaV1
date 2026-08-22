"""Medicine knowledge: AI-fetched draft in, caretaker-confirmed fact out.

Invariant 9 is the whole point of this module. A Qwen fetch is a DRAFT. It is
never surfaced to a patient and never usable by the agent until a caretaker
has reviewed and confirmed it on the dashboard. At reply-time the agent may
call get_confirmed() and nothing else.

Signatures frozen in AGENTS.md section 9.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_PHASE = "Phase 3 - agent understanding"


@dataclass
class MedicineInfoDraft:
    """Structured medicine information, confirmed or not.

    Mirrors the medicine_reference table. `confirmed` is False for anything
    that came back from Qwen and has not yet been through a caretaker.
    """

    canonical_name: str
    purpose_ur: str | None = None
    purpose_en: str | None = None
    food_rule: str | None = None
    common_timing: str | None = None
    aliases: list[str] = field(default_factory=list)
    source: str = "ai_fetched"
    confirmed: bool = False


async def fetch_draft(name: str) -> MedicineInfoDraft:
    """Ask Qwen what this medicine is for. Returns a DRAFT.

    NEVER writes confirmed=true. NEVER called from the patient-facing reply
    path - a fetch happens only when a caretaker adds a medicine on the
    dashboard.
    """
    raise NotImplementedError(_PHASE)


def get_confirmed(name: str) -> MedicineInfoDraft | None:
    """Read a confirmed medicine_reference row. DB read only, no AI call.

    This is the ONLY function the agent may call at reply-time. Returns None
    when no confirmed row exists, and the agent must then say so rather than
    invent an answer.
    """
    raise NotImplementedError(_PHASE)


async def save_confirmed(name: str, info: MedicineInfoDraft, caretaker_id: str) -> None:
    """Write the row with confirmed=true. Called only from the dashboard's
    confirm action (Phase 4)."""
    raise NotImplementedError(_PHASE)
