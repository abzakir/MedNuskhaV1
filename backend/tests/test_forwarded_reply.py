"""A forwarded message is not the patient answering.

On 2026-08-30 a patient forwarded a voice note back to us and the agent
replied "Shukriya, polymalt le li - likh liya hai", recorded the dose as
TAKEN and switched off the escalation that would have caught it. She had
taken nothing; she had pressed forward.

A wrong "she took it" is the worst error this system can make. It is the one
outcome that both corrupts the record a doctor will read and stops anybody
being told. So nothing that changes the record may come from a forwarded
message - it gets a question instead.

An emergency still gets through. Erring towards fetching a human is the one
direction this system is allowed to err in.

    pytest backend/tests/test_forwarded_reply.py -v
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.interpret import (STATE_CHANGING, Intent,  # noqa: E402
                                 _not_an_answer, interpret)
from app.whatsapp.parser import parse_message  # noqa: E402


class Patient:
    id = "p1"
    name = "Ammi"
    language = "ur"


class Dose:
    def __init__(self, name="polymalt"):
        self.id = "dose-1"
        self.medicine_name = name
        self.medicine_label = name
        self.state = "AWAITING_REPLY"


class Msg:
    def __init__(self, text, forwarded=False, payload=None):
        self.text = text
        self.payload = payload
        self.forwarded = forwarded


# ==========================================================================
# the flag arrives at all
# ==========================================================================


def test_01_the_bridge_flag_reaches_the_parser():
    assert parse_message({"id": "a", "from": "923001234567", "type": "audio",
                          "forwarded": True}).forwarded is True


def test_02_an_ordinary_message_is_not_forwarded():
    assert parse_message({"id": "b", "from": "923001234567", "type": "text",
                          "text": "haan"}).forwarded is False


# ==========================================================================
# the rule
# ==========================================================================


@pytest.mark.parametrize("kind", STATE_CHANGING)
def test_03_nothing_that_changes_the_record_survives_a_forward(kind):
    assert _not_an_answer(kind, forwarded=True)


@pytest.mark.parametrize("kind", STATE_CHANGING)
def test_04_the_same_message_typed_out_is_fine(kind):
    assert not _not_an_answer(kind, forwarded=False)


def test_05_an_emergency_is_never_suppressed():
    assert not _not_an_answer("emergency", forwarded=True)


def test_06_taken_is_one_of_the_kinds_being_guarded():
    """The bug was a false TAKEN specifically - keep it named here."""
    assert "taken" in STATE_CHANGING
    assert "stop" in STATE_CHANGING, "a forwarded STOP must not halt reminders"


# ==========================================================================
# end to end through interpret()
# ==========================================================================


def _interpret(msg, doses):
    return asyncio.run(interpret(msg, Patient(), doses))


def test_07_a_forwarded_confirmation_asks_instead_of_recording():
    """The reported failure, in one test."""
    intent = _interpret(Msg("le li hai", forwarded=True), [Dose()])
    assert intent.kind == "unclear", "a forward must not confirm a dose"
    assert intent.forwarded is True


def test_08_the_same_words_typed_do_confirm():
    intent = _interpret(Msg("le li hai", forwarded=False), [Dose()])
    assert intent.kind == "taken"
    assert intent.dose_id == "dose-1"


def test_09_a_forwarded_stop_does_not_stop_anything():
    intent = _interpret(Msg("band kar do", forwarded=True), [Dose()])
    assert intent.kind != "stop"


def test_10_a_forwarded_emergency_still_fires():
    intent = _interpret(Msg("seene mein dard", forwarded=True), [Dose()])
    assert intent.kind == "emergency"


def test_11_a_tapped_button_is_still_authoritative():
    """A payload carries the dose id explicitly - it cannot be a forward."""
    payload = "TAKEN:11111111-1111-4111-8111-111111111111"
    intent = _interpret(Msg("Le li", forwarded=True, payload=payload), [Dose()])
    assert intent.kind == "taken"


def test_12_the_intent_defaults_to_not_forwarded():
    """Every other caller builds an Intent without knowing about this."""
    assert Intent(kind="taken", dose_id=None, reason=None,
                  confidence=1.0).forwarded is False
