"""The reply to the opt-in message, which is the one way back in.

Section 4.4 forbids sending anything to a patient who has not opted in, and
`PATCH /api/patients/{id}` clears the opt-in whenever the WhatsApp number
changes - which is the whole point of that endpoint, because a new number is a
new handset belonging to somebody who has agreed to nothing.

The intro message then says, in as many words, "reply HAAN to begin". Nothing
in the system read that answer: "HAAN" resolved to a dose confirmation, found
no open dose (there are none - materialisation skips an opted-out patient),
and fell through to "samajh nahi aaya". The patient was stranded with
reminders permanently off and no way back short of a caretaker pressing a
button meant for something else.

These are pure - the database and WhatsApp are both stubbed - because what is
being pinned is the routing decision, not the writes.

    pytest backend/tests/test_optin.py -v
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import respond as responder  # noqa: E402
from app.agent.interpret import Intent, is_affirmative  # noqa: E402


# ==========================================================================
# is_affirmative - what the intro message actually asks for
# ==========================================================================


@pytest.mark.parametrize("text", [
    "HAAN", "haan", "Haan ji", "han", "ji haan", "ok", "theek hai",
    "yes", "Yes", "ہاں", "جی ہاں",
])
def test_01_the_words_a_patient_answers_with(text):
    assert is_affirmative(text)


@pytest.mark.parametrize("text", [
    "", "   ", "nahi", "abhi nahi", "kya hai ye",
    # Long enough that a stray "ok" inside it is not consent to anything.
    "mujhe nahi pata ye kya hai aur main ok nahi hoon is baare mein",
])
def test_02_what_is_not_a_yes(text):
    assert not is_affirmative(text)


# ==========================================================================
# routing - a patient who has not opted in is answering ONE question
# ==========================================================================


class FakePatient:
    def __init__(self, opted_in: bool, stopped: bool = False):
        self.id = "patient-1"
        self.name = "Ammi"
        self.language = "ur"
        self.whatsapp_number = "923001234567"
        self.opted_in = opted_in
        self.stopped = stopped


@pytest.fixture
def routed(monkeypatch):
    """Run respond() with every side effect replaced by a recording stub."""
    calls: dict = {"sent": [], "opted_in": False, "materialised": False,
                   "stopped": False, "alerts": []}

    monkeypatch.setattr(responder, "_caretakers_for",
                        lambda pid: [{"id": "c1", "name": "Usman",
                                      "phone": "923009999999",
                                      "relation": "beta", "language": "ur"}])
    monkeypatch.setattr(responder, "_known_texts", lambda pid: ["Panadol 500mg"])
    # Without this the guardrail reads the medicine corpus out of the live
    # database, and a "pure" test takes four seconds and fails whenever the
    # network hiccups. `make test` promises no services.
    monkeypatch.setattr(responder, "_all_medicine_names", lambda: [])
    monkeypatch.setattr(responder, "open_doses_for", lambda pid, *a: [])
    monkeypatch.setattr(responder, "_set_opted_in",
                        lambda pid: calls.__setitem__("opted_in", True))
    monkeypatch.setattr(responder, "_set_stopped",
                        lambda pid: calls.__setitem__("stopped", True))
    monkeypatch.setattr(responder, "_record_symptom",
                        lambda *a, **k: None)

    async def fake_send(to, body):
        calls["sent"].append(body)
        return "stub"

    async def fake_alert(caretakers, *, reason, patient, words):
        calls["alerts"].append(reason)

    monkeypatch.setattr(responder.wa, "send_text", fake_send)
    monkeypatch.setattr(responder, "_alert_caretakers", fake_alert)

    # materialise_doses is imported inside the function, so patch it at source.
    from app.scheduler import ticker
    monkeypatch.setattr(ticker, "materialise_doses",
                        lambda *a, **k: calls.__setitem__("materialised", True))

    def run(intent: Intent, patient: FakePatient):
        asyncio.run(responder.respond(intent, patient))
        return calls

    return run


def _intent(kind: str, text: str) -> Intent:
    return Intent(kind=kind, dose_id=None, reason=None, confidence=1.0, text=text)


def test_03_haan_opts_the_patient_in(routed):
    calls = routed(_intent("taken", "HAAN"), FakePatient(opted_in=False))
    assert calls["opted_in"] is True
    assert calls["materialised"] is True, \
        "their doses were never materialised while opted out - they need creating now"
    # Asserted on meaning, not on one word of the copy - this used to check
    # for "shukriya" and broke the moment the greeting was reworded.
    assert any("mednuskha" in body.lower() for body in calls["sent"]),         "the first thing a patient hears back should say who we are"


def test_04_anything_else_re_asks_rather_than_guessing(routed):
    calls = routed(_intent("unclear", "ye kya hai"), FakePatient(opted_in=False))
    assert calls["opted_in"] is False
    assert any("HAAN" in body for body in calls["sent"]), \
        "the only thing to say to a patient who has not opted in is the intro"


def test_05_a_refusal_is_honoured_as_a_stop(routed):
    calls = routed(_intent("stop", "band kar do"), FakePatient(opted_in=False))
    assert calls["opted_in"] is False
    assert calls["stopped"] is True


def test_06_an_emergency_outranks_the_opt_in_gate(routed):
    """Section 11: a chest-pain message gets the fixed emergency copy, always.

    Whether the patient ever agreed to reminders has nothing to do with it.
    """
    calls = routed(_intent("emergency", "seene mein dard"),
                   FakePatient(opted_in=False))
    assert any("foran" in body for body in calls["sent"])
    assert "emergency" in calls["alerts"]
    assert calls["opted_in"] is False


def test_07_an_opted_in_patient_is_untouched_by_any_of_this(routed):
    """The gate must not stand between an ordinary patient and a dose reply."""
    calls = routed(_intent("later", "abhi nahi"), FakePatient(opted_in=True))
    assert not any("HAAN" in body for body in calls["sent"])
    assert calls["opted_in"] is False        # nothing was written


def test_08_the_unit_suite_never_reaches_the_database(monkeypatch):
    """`make test` promises "no services", and it has to stay true.

    `_send_checked` grew a call that reads the medicine corpus, and every test
    exercising a reply started making a round trip to Supabase - four seconds
    each, and red whenever the network blinked. A guardrail that cannot reach
    the database must fall back to its seed list, not raise.
    """
    from app.agent import respond as r

    r._MEDICINE_NAMES = ([], 0.0)

    def no_database():
        raise RuntimeError("the unit suite must not open a connection")

    monkeypatch.setattr(r, "session_scope", no_database)
    assert r._all_medicine_names() == []


# ==========================================================================
# asking for consent has to actually wait for it
# ==========================================================================


def test_09_sending_the_intro_puts_them_back_to_awaiting(monkeypatch):
    """The gate is useless if nothing ever opens it.

    A patient added on the dashboard starts opted_in=True, so the gate in
    respond() never fired and the HAAN came back through the ordinary reply
    path. Observed on a real phone 2026-09-03: a patient answered the intro
    and was told "Thank you CR sahab ji. zahr 200kg taken - it's noted."
    A dose was recorded as swallowed because somebody said hello.
    """
    import asyncio

    from app.api import routes

    class P:
        id = "p1"; name = "CR sahab"; whatsapp_number = "923001234568"
        language = "ur"; opted_in = True
        opted_in_at = "some-earlier-time"; family_id = "f1"

    class C:
        id = "c1"; name = "Affan"; family_id = "f1"

    class S:
        def __init__(self): self.committed = False
        def add(self, _o): pass
        def commit(self): self.committed = True

    patient, session = P(), S()
    monkeypatch.setattr(routes, "_owned_patient", lambda *a, **k: patient)

    async def fake_template(**_k):
        return "stub-id"

    import app.whatsapp.client as wa
    monkeypatch.setattr(wa, "send_template", fake_template)

    out = asyncio.run(routes.send_optin("p1", C(), session))

    assert out["sent"] and out["awaiting_reply"] is True
    assert patient.opted_in is False, "asking for consent must wait for it"
    assert patient.opted_in_at is None
    assert session.committed


def test_10_and_then_haan_lands_on_the_welcome(routed):
    """The other half, joined up: awaiting -> HAAN -> welcome, not a dose ack."""
    calls = routed(_intent("taken", "HAAN"), FakePatient(opted_in=False))
    assert calls["opted_in"] is True
    body = " ".join(calls["sent"]).lower()
    assert "mednuskha" in body, "the first thing they hear back should say who we are"
    assert "taken - it's noted" not in body
    assert "le li" not in body, "a greeting is not a dose confirmation"
