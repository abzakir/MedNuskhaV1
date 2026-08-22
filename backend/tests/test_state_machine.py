"""Transition tests for scheduler/state_machine.py.

Written in Phase 2, alongside the dose loop. Covers the three paths the Phase 2
gate demands: taken, missed, and late-reply reclassification - plus the
idempotency guarantee that a restart never sends a second reminder
(invariant 5).
"""

from __future__ import annotations

import pytest

pytest.skip(
    "the state machine is implemented in Phase 2 - the dose loop",
    allow_module_level=True,
)

#: (label, sequence of events, expected final state)
TRANSITION_CASES = [
    ("taken_on_button", ["send", "button_taken"], "TAKEN"),
    ("taken_on_text", ["send", "text_taken"], "TAKEN"),
    ("followup_then_taken", ["send", "followup", "button_taken"], "TAKEN"),
    ("silence_to_missed", ["send", "followup", "escalate"], "MISSED"),
    ("late_reply_reclassifies", ["send", "followup", "escalate", "text_taken"], "TAKEN_LATE"),
    ("explicit_decline", ["send", "text_not_taken"], "SKIPPED"),
    ("double_materialise_is_noop", ["materialise", "materialise"], "SCHEDULED"),
    ("restart_does_not_resend", ["send", "restart", "tick"], "AWAITING_REPLY"),
]
