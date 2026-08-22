"""Programmatic safety check on every outbound message, before it is sent.

Invariant 8: the agent never diagnoses, changes a dose, recommends or
substitutes a medicine, or interprets a symptom or test result. Enforced in
three places - the system prompt, this module, and tests/test_guardrails.py.

Blocks and substitutes the fixed refusal when a draft:
  * contains a dosage figure not matching the patient's schedule rows
    (invariant 10: no outbound message contains a dose figure not in the DB);
  * recommends, substitutes, increases, decreases, starts or stops a medicine;
  * offers a diagnosis or interprets a symptom;
  * answers an emergency keyword (chest pain, saans, behosh, bleeding) with
    anything other than the fixed emergency copy plus an immediate caretaker
    alert.

The fixed refusal and the emergency copy live in i18n/strings.py.
"""

from __future__ import annotations

from dataclasses import dataclass

_PHASE = "Phase 3 - agent understanding"

#: Any of these in an inbound message forces the emergency path.
EMERGENCY_KEYWORDS_UR = ("saans", "behosh", "seene mein dard", "khoon")
EMERGENCY_KEYWORDS_EN = ("chest pain", "unconscious", "bleeding", "breathing")


@dataclass
class GuardrailResult:
    """Outcome of checking one draft message."""

    allowed: bool
    #: The message to actually send - the draft when allowed, the fixed
    #: refusal when not.
    message: str
    #: Which rule fired, for the log and for the caretaker alert.
    violated_rule: str | None
    #: True when the caretaker must be notified regardless of the reply.
    alert_caretaker: bool


def check(draft: str, patient, intent=None) -> GuardrailResult:
    """Check one outbound draft. Called on every message with no exceptions."""
    raise NotImplementedError(_PHASE)


def contains_unknown_dose_figure(draft: str, patient) -> bool:
    """True if the draft states a dose figure not present in that patient's
    schedule rows (invariant 10)."""
    raise NotImplementedError(_PHASE)


def is_emergency(text: str) -> bool:
    """True if the inbound text trips an emergency keyword in any language."""
    raise NotImplementedError(_PHASE)
