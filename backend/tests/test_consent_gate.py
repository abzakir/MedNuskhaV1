"""Nothing reaches a patient who has not agreed (section 4.4).

The guard this replaces was ALLOWED_NUMBERS: a hand-curated env list. It
caught a mistyped digit only because a human had to type the number twice, and
it blocked every new tester until somebody edited .env and restarted the
bridge - which is how three real patients silently failed to receive anything
on 2026-09-03.

Consent is the better guard, because a wrong digit is still a perfectly valid
`patient` row. "Is this number registered?" would have allowed it. "Has a
human on this handset actually replied?" does not.

The one thing that must still get through is the intro itself. It is how you
ask, so it cannot require an answer - and it names no medicine, no dose and no
condition, so a mistyped number costs one polite sentence and then silence.

    pytest backend/tests/test_consent_gate.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.whatsapp import client as wa  # noqa: E402


class Patient:
    def __init__(self, name, number, opted_in=False, stopped=False):
        self.name = name
        self.whatsapp_number = number
        self.opted_in = opted_in
        self.stopped = stopped


def _db(patients):
    """A session_scope() standing in for a patient lookup by number."""
    class Q:
        def __init__(self, rows): self.rows = rows
        def filter(self, *_a, **_k): return self
        def first(self): return self.rows[0] if self.rows else None

    class Session:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def query(self, _model): return Q(patients)
    return lambda: Session()


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    # settings is a pydantic model whose computed fields are read-only, so it
    # is replaced wholesale rather than patched attribute by attribute. This
    # also keeps the test independent of whether a real DATABASE_URL is set.
    from types import SimpleNamespace
    monkeypatch.setattr(wa, "settings", SimpleNamespace(database_configured=True))


# ==========================================================================
# the bootstrap: asking must always be possible
# ==========================================================================


def test_01_the_intro_reaches_someone_who_has_agreed_to_nothing(monkeypatch):
    """Otherwise it deadlocks - they can never reply HAAN to a message we
    refused to send."""
    monkeypatch.setattr(wa, "session_scope",
                        _db([Patient("Ammi", "923013494452", opted_in=False)]))
    allowed, _ = wa.may_send("923013494452", "patient_optin")
    assert allowed


def test_02_but_nothing_else_does(monkeypatch):
    monkeypatch.setattr(wa, "session_scope",
                        _db([Patient("Ammi", "923013494452", opted_in=False)]))
    for template in ("dose_reminder", "dose_followup", "caretaker_alert", None):
        allowed, why = wa.may_send("923013494452", template)
        assert not allowed, f"{template} should have been refused"
        assert "not opted in" in why


# ==========================================================================
# after they agree
# ==========================================================================


def test_03_a_confirmed_patient_gets_everything(monkeypatch):
    monkeypatch.setattr(wa, "session_scope",
                        _db([Patient("Ammi", "923013494452", opted_in=True)]))
    for template in ("dose_reminder", "dose_followup", None):
        assert wa.may_send("923013494452", template)[0]


def test_04_stop_outranks_consent(monkeypatch):
    """A patient who said STOP has withdrawn it - even the intro stays out."""
    monkeypatch.setattr(wa, "session_scope",
                        _db([Patient("Ammi", "923013494452",
                                     opted_in=True, stopped=True)]))
    for template in ("dose_reminder", "patient_optin", None):
        allowed, why = wa.may_send("923013494452", template)
        assert not allowed and "STOP" in why


# ==========================================================================
# everyone who is not a patient
# ==========================================================================


def test_05_caretakers_are_not_gated(monkeypatch):
    """They registered themselves, and the missed-dose alert is the product."""
    monkeypatch.setattr(wa, "session_scope", _db([]))
    assert wa.may_send("923001776024", None)[0]


def test_06_a_broken_check_does_not_silence_the_system(monkeypatch):
    """A database wobble must not stop every reminder - the bridge allowlist
    is still behind this."""
    def explode():
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(wa, "session_scope", explode)
    assert wa.may_send("923013494452", "dose_reminder")[0]


def test_07_an_empty_number_is_never_sent_to(monkeypatch):
    monkeypatch.setattr(wa, "session_scope", _db([]))
    assert not wa.may_send("", None)[0]
    assert not wa.may_send(None, None)[0]


def test_08_the_consent_template_set_is_minimal():
    """Every name in here is a message a stranger can receive. Keep it at one."""
    assert wa.CONSENT_TEMPLATES == frozenset({"patient_optin"})
