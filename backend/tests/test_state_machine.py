"""Which dose a reply belongs to, and which transitions are legal.

Two things are pinned here.

**Dose resolution.** WhatsApp removed interactive buttons for non-official
clients, so the dose id no longer travels back in a payload (PROJECT_LOG,
2026-08-23). Section 5.2 still forbids inferring the dose from timing, so
replies are resolved against the doses actually awaiting an answer. These
tests are pure - no database - because the rule is pure.

**Transitions.** The state table itself is exercised against a live database
by the Phase 2 verification; the legal-move table is asserted here so a new
state cannot be added without deciding where it may go.

    pytest backend/tests/test_state_machine.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.interpret import resolve_dose  # noqa: E402
from app.models import DOSE_STATES, DOSE_TERMINAL_STATES  # noqa: E402
from app.scheduler.state_machine import ALLOWED  # noqa: E402


class Dose:
    """The shape resolve_dose reads: an id, a state, a medicine name."""

    def __init__(self, id: str, state: str, medicine: str = "Panadol"):
        self.id = id
        self.state = state
        self.medicine_name = medicine


# ==========================================================================
# dose resolution - the replacement for invariant 2
# ==========================================================================


def test_01_no_open_doses_resolves_to_nothing():
    """A reply with nothing pending is a general message, not a confirmation."""
    dose_id, ambiguous = resolve_dose("haan le li", None, [])
    assert dose_id is None
    assert not ambiguous


def test_02_one_open_dose_is_unambiguous():
    doses = [Dose("a", "AWAITING_REPLY")]
    assert resolve_dose("haan le li", None, doses) == ("a", False)


def test_03_an_explicit_payload_always_wins():
    """If a button ever works again, its id beats every heuristic here."""
    real = "11111111-2222-3333-4444-555555555555"
    doses = [Dose("a", "AWAITING_REPLY"), Dose("b", "AWAITING_REPLY", "Metformin")]
    assert resolve_dose("anything", f"TAKEN:{real}", doses) == (real, False)


def test_04_a_missed_dose_does_not_make_an_awaiting_one_ambiguous():
    """THE REGRESSION. Observed on a real phone, 2026-08-23.

    One dose awaiting a reply plus one missed earlier that day counted as two
    "open" doses, so every single reply came back ambiguous and the patient
    got "samajh nahi aaya" to everything. Missed doses accumulate, so this got
    worse by the day.
    """
    doses = [Dose("awaiting", "AWAITING_REPLY"), Dose("missed", "MISSED")]
    dose_id, ambiguous = resolve_dose("Abhi nahi", None, doses)
    assert dose_id == "awaiting", "the dose actually awaiting an answer must win"
    assert not ambiguous, "one awaiting dose is never ambiguous"


def test_05_several_missed_doses_still_do_not_drown_out_an_awaiting_one():
    """By day three a patient may have many missed doses. None of them compete."""
    doses = [Dose("awaiting", "SENT")] + [
        Dose(f"m{i}", "MISSED") for i in range(5)
    ]
    assert resolve_dose("nhe li", None, doses) == ("awaiting", False)


def test_06_a_missed_dose_is_used_when_nothing_else_is_open():
    """Section 4.8: a late confirmation must still land, turning MISSED into
    TAKEN_LATE."""
    doses = [Dose("missed", "MISSED")]
    assert resolve_dose("haan le li", None, doses) == ("missed", False)


def test_07_two_doses_genuinely_awaiting_are_ambiguous():
    """Two medicines due at once and a bare "haan" - ask, never guess."""
    doses = [Dose("a", "AWAITING_REPLY", "Panadol"),
             Dose("b", "AWAITING_REPLY", "Metformin")]
    dose_id, ambiguous = resolve_dose("haan le li", None, doses)
    assert dose_id is None
    assert ambiguous


def test_08_naming_the_medicine_breaks_the_tie():
    """Which is why every reminder names the medicine and its strength."""
    doses = [Dose("a", "AWAITING_REPLY", "Panadol"),
             Dose("b", "AWAITING_REPLY", "Metformin")]
    assert resolve_dose("Metformin le li hai", None, doses) == ("b", False)
    assert resolve_dose("panadol le li", None, doses) == ("a", False)


def test_09_a_short_medicine_name_is_not_matched_loosely():
    """Matching on three letters would fire on ordinary words."""
    doses = [Dose("a", "AWAITING_REPLY", "ABC"), Dose("b", "AWAITING_REPLY", "XYZ")]
    dose_id, ambiguous = resolve_dose("haan le li hai", None, doses)
    assert dose_id is None and ambiguous


def test_10_reminded_again_counts_as_awaiting():
    """A dose that got the follow-up is still waiting for an answer."""
    doses = [Dose("a", "REMINDED_AGAIN"), Dose("m", "MISSED")]
    assert resolve_dose("le li", None, doses) == ("a", False)


# ==========================================================================
# the transition table
# ==========================================================================


def test_11_every_state_has_a_rule():
    """A state with no entry would be silently un-transitionable."""
    for state in DOSE_STATES:
        assert state in ALLOWED, f"{state} has no transition rule"


def test_12_terminal_states_are_final_except_missed():
    """MISSED is the one terminal state that can still move - a late
    confirmation reclassifies it (section 4.8)."""
    for state in DOSE_TERMINAL_STATES:
        if state == "MISSED":
            assert ALLOWED[state] == {"TAKEN_LATE"}
        else:
            assert ALLOWED[state] == set(), f"{state} should be final"


def test_13_no_rule_points_at_a_state_that_does_not_exist():
    for state, targets in ALLOWED.items():
        for target in targets:
            assert target in DOSE_STATES, f"{state} -> unknown state {target}"


def test_14_a_taken_dose_cannot_go_backwards():
    """This is what stops a late webhook retry dragging a confirmed dose back
    into the escalation chain."""
    for backwards in ("SCHEDULED", "SENT", "AWAITING_REPLY", "REMINDED_AGAIN",
                      "MISSED"):
        assert backwards not in ALLOWED["TAKEN"]
        assert backwards not in ALLOWED["TAKEN_LATE"]


def test_15_a_scheduled_dose_can_only_be_sent_skipped_or_missed():
    """A dose cannot jump straight to TAKEN without ever being sent."""
    assert ALLOWED["SCHEDULED"] == {"SENT", "SKIPPED", "MISSED"}
