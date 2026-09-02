"""What a caretaker is told when a WhatsApp number is already in use.

`patient.whatsapp_number` is UNIQUE across the whole system, and has to be:
two families both reminding one handset would talk over each other, and a
reply could not be attributed to either.

The message about it was a dead end. Reported 2026-09-02: a caretaker signed
in with a second Google account, saw "Nobody added yet", typed their mother's
number and was told "a patient with that WhatsApp number already exists" -
with no way to find her and nothing to do next. She was in the first
account's family, invisible from this one.

    pytest backend/tests/test_number_taken.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.routes import _number_taken  # noqa: E402


class Patient:
    def __init__(self, name, family_id):
        self.name = name
        self.family_id = family_id


class Caretaker:
    def __init__(self, family_id):
        self.family_id = family_id


MINE = Caretaker("family-1")


def test_01_a_patient_i_can_already_see_is_named():
    """Inside my own family there is nothing to hide and something to point at."""
    message = _number_taken(Patient("Ammi", "family-1"), MINE)
    assert "Ammi" in message
    assert "patient list" in message


def test_02_another_familys_patient_is_never_named():
    """Naming them would leak one account's patients to another."""
    message = _number_taken(Patient("Ammi", "family-2"), MINE)
    assert "Ammi" not in message


def test_03_but_the_caretaker_is_told_where_it_went():
    """The dead end was not knowing it was elsewhere at all."""
    message = _number_taken(Patient("Ammi", "family-2"), MINE)
    assert "different" in message.lower() or "another" in message.lower()
    assert "account" in message.lower()


def test_04_and_is_given_a_way_out():
    """Two ways, both actionable without help: use that account, or free it."""
    message = _number_taken(Patient("Ammi", "family-2"), MINE).lower()
    assert "sign in" in message
    assert "remove" in message


def test_05_the_two_cases_do_not_read_the_same():
    """Telling them apart is the entire fix."""
    assert (_number_taken(Patient("Ammi", "family-1"), MINE)
            != _number_taken(Patient("Ammi", "family-2"), MINE))
