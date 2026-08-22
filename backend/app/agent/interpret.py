"""Turn a messy human reply into exactly one Intent (AGENTS.md section 11).

Uses Qwen via Alibaba Model Studio (DashScope). Understands Urdu script,
Roman Urdu and English.

Always runs in a background task, never on the webhook request path - Qwen
latency inside the webhook blocks the 2-second 200 (section 17).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

_PHASE = "Phase 3 - agent understanding"

#: Below this, interpret returns "unclear" and respond asks one short
#: clarifying question. The agent never guesses (section 11).
CONFIDENCE_FLOOR = 0.6


@dataclass
class Intent:
    """What the patient meant, and which dose it refers to."""

    kind: Literal[
        "taken", "not_taken", "later", "question",
        "symptom", "emergency", "unclear", "stop",
    ]
    dose_id: str | None
    reason: str | None
    confidence: float


async def interpret(msg, patient, open_doses) -> Intent:
    """Classify one InboundMessage against the patient's open doses.

    `msg` is a whatsapp.parser.InboundMessage, `patient` a models.Patient,
    `open_doses` the list of that patient's non-terminal DoseEvents.

    The dose id comes from the button payload when there is one (invariant 2);
    it is never inferred from timing alone.
    """
    raise NotImplementedError(_PHASE)
