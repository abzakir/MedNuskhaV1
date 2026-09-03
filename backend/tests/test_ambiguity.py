"""Which dose a reply means, and what to say when we cannot tell.

CR sahab said "Yes, I have taken this" into WhatsApp on 2026-09-03. Whisper
transcribed it perfectly. The model classified it as `taken` with high
confidence. He was told "Sorry, I didn't catch that" - three times in ninety
seconds, twice more by voice, and the question that came back named one of his
two medicines at random so answering it could not have helped either.

Nothing had failed to understand him. Three doses were open across two
medicines, `resolve_dose` counted DOSES rather than MEDICINES, and everything
downstream treated "I don't know which" as "I don't know what".

Two rules come out of that:

  1. ambiguity is about the medicine. Two open doses of one medicine are not
     a question - "I took it" can only mean that one, and the newest is what
     they were last reminded of.
  2. when it IS ambiguous, say so and name every option. Claiming not to have
     understood somebody who was perfectly clear makes them repeat
     themselves, which produces the same answer again.

    pytest backend/tests/test_ambiguity.py -v
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.interpret import (distinct_medicines,  # noqa: E402
                                 resolve_dose)

NOW = datetime(2026, 9, 3, 18, 55, tzinfo=timezone.utc)


class Dose:
    def __init__(self, id, medicine, state, minutes_ago, label=None):
        self.id = id
        self.medicine_name = medicine
        self.medicine_label = label or medicine
        self.state = state
        self.scheduled_at = NOW - timedelta(minutes=minutes_ago)


def _cr_sahab():
    """Exactly what was open when it went wrong."""
    return [
        Dose("d1", "panadol", "AWAITING_REPLY", 5),
        Dose("d2", "zahr", "AWAITING_REPLY", 5, label="zahr 200kg"),
        Dose("d3", "zahr", "REMINDED_AGAIN", 16, label="zahr 200kg"),
    ]


# ==========================================================================
# one medicine is never a question, however many doses are open
# ==========================================================================


def test_01_two_doses_of_one_medicine_resolve_to_the_newest():
    doses = [Dose("old", "zahr", "REMINDED_AGAIN", 16),
             Dose("new", "zahr", "AWAITING_REPLY", 5)]
    dose_id, ambiguous = resolve_dose("le li", None, doses)
    assert not ambiguous, "one medicine cannot be ambiguous"
    assert dose_id == "new", "the newest is the one they were just reminded of"


def test_02_a_twice_daily_prescription_is_answerable():
    """The regression: a patient on one medicine, twice a day, could not
    confirm a dose at all once both were open."""
    doses = [Dose("morning", "zahr", "REMINDED_AGAIN", 700),
             Dose("evening", "zahr", "AWAITING_REPLY", 5)]
    assert resolve_dose("Yes, I have taken this.", None, doses)[1] is False


# ==========================================================================
# two medicines, none named - ask, and know that you are asking
# ==========================================================================


def test_03_two_medicines_and_no_name_is_ambiguous():
    dose_id, ambiguous = resolve_dose("le li", None, _cr_sahab())
    assert ambiguous and dose_id is None


def test_04_the_options_offered_are_de_duplicated():
    """Two zahr doses must not produce "zahr or zahr or panadol"."""
    options = distinct_medicines(_cr_sahab())
    assert len(options) == 2
    assert sorted(options) == ["panadol", "zahr 200kg"]


# ==========================================================================
# naming one resolves it, to that medicine's newest dose
# ==========================================================================


def test_05_naming_a_medicine_picks_its_newest_dose():
    dose_id, ambiguous = resolve_dose("zahr le li", None, _cr_sahab())
    assert not ambiguous
    assert dose_id == "d2", "d2 is newer than d3, and both are zahr"


def test_06_naming_the_other_one_picks_that():
    dose_id, ambiguous = resolve_dose("panadol le li hai", None, _cr_sahab())
    assert not ambiguous and dose_id == "d1"


# ==========================================================================
# unchanged rules
# ==========================================================================


def test_07_a_payload_still_beats_everything():
    payload = "TAKEN:11111111-1111-4111-8111-111111111111"
    dose_id, ambiguous = resolve_dose("anything", payload, _cr_sahab())
    assert not ambiguous
    assert dose_id == "11111111-1111-4111-8111-111111111111"


def test_08_nothing_open_is_not_ambiguous():
    assert resolve_dose("le li", None, []) == (None, False)


def test_09_missed_doses_do_not_compete_with_a_live_one():
    """Missed doses accumulate; counting them made every reply ambiguous."""
    doses = [Dose("missed", "panadol", "MISSED", 900),
             Dose("live", "zahr", "AWAITING_REPLY", 5)]
    dose_id, ambiguous = resolve_dose("le li", None, doses)
    assert not ambiguous and dose_id == "live"


# ==========================================================================
# the spellings people actually use
# ==========================================================================


def test_10_real_roman_urdu_spellings_are_understood():
    """Observed in the wild: "Lely Mene" from Whisper, "Layli mainay" typed.

    Both mean "le li maine". The model scored the typed one at 0.10 and the
    patient was told we did not understand.
    """
    from app.agent.interpret import _fast_intent

    for text in ("Layli mainay", "Lely Mene", "leli", "le li", "lelly"):
        assert _fast_intent(text) == ("taken", 0.9), text


def test_11_a_denial_is_never_read_as_a_confirmation():
    """The one false positive that would actually hurt somebody."""
    from app.agent.interpret import _fast_intent

    for text in ("nahi li", "maine nahi li", "abhi tak nahi li"):
        got = _fast_intent(text)
        assert got is None or got[0] != "taken", f"{text} -> {got}"
