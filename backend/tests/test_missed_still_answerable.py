"""A dose that has gone MISSED is still something the patient can answer.

Maani ji answered "abhi nahi" at 11:54pm and was told, correctly, that we would
remind her again. A minute later she said she had taken it - by voice, three
times, and then in plain text. Every single reply came back "Maaf kijiye ga,
samajh nahi aaya. Kya aap ne apni dawai le li hai?". Seen on a real phone,
2026-09-05.

Nothing had failed to understand her. Two halves of the system disagreed about
which doses existed:

  * `interpret` is handed `open_doses_for(patient_id)` - MISSED included, so a
    late confirmation can still land (section 4.8).
  * `_on_unclear` re-fetched with `include_missed=False`.

So once the dose had escalated, interpret could see two missed medicines, call
the reply ambiguous, and hand over to a branch that saw NO doses at all. The
"which one have you taken?" question - written for exactly this case - needs
more than one option to fire, got zero, and fell through to the generic line.
Nothing changed between attempts, so it failed identically every time.

The rule: the branch that has to ask WHICH medicine must see the same doses
that made the question necessary in the first place.

    pytest backend/tests/test_missed_still_answerable.py -v
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import respond  # noqa: E402
from app.agent.interpret import Intent, resolve_dose  # noqa: E402


class Patient:
    id = "p1"
    name = "Maani"
    language = "ur"
    whatsapp_number = "923001234567"


class Dose:
    def __init__(self, id, medicine, state, label=None):
        self.id = id
        self.medicine_name = medicine
        self.medicine_label = label or medicine
        self.state = state


def _missed_two_medicines():
    """What was actually open when it went wrong: nothing awaiting, two missed."""
    return [Dose("d1", "panadol", "MISSED", "Panadol 500mg"),
            Dose("d2", "polymalt", "MISSED", "polymalt syrup")]


def _unclear(text="haan mene le li hai"):
    return Intent(kind="unclear", dose_id=None, reason=text, confidence=0.5,
                  medicine=None, text=text, forwarded=False, ambiguous=True)


def _run_unclear(monkeypatch, doses, *, worded=None):
    """Drive _on_unclear, capturing what it would have sent and how it asked."""
    sent: list[str] = []
    asked: dict = {}

    def fake_open(patient_id, include_missed=True):
        # Behaves like the real one: asking to exclude MISSED really does
        # exclude them, so the message-content tests below fail on the old
        # code rather than passing on a stub that ignored the flag.
        asked["include_missed"] = include_missed
        if include_missed:
            return list(doses)
        return [d for d in doses if d.state != "MISSED"]

    async def fake_send(patient, draft, **_kw):
        sent.append(draft)

    async def fake_chat(*_a, **_k):
        return worded

    monkeypatch.setattr(respond, "open_doses_for", fake_open)
    monkeypatch.setattr(respond, "_send_checked", fake_send)
    monkeypatch.setattr(respond.wa, "send_text", fake_send)
    monkeypatch.setattr(respond.llm, "try_chat", fake_chat)

    asyncio.run(respond._on_unclear(_unclear(), Patient(), "ur", [], "Usman", []))
    return sent, asked


# ==========================================================================
# the fix itself
# ==========================================================================


def test_01_on_unclear_sees_the_same_doses_interpret_saw(monkeypatch):
    """It must not filter MISSED away behind interpret's back."""
    _, asked = _run_unclear(monkeypatch, _missed_two_medicines())
    assert asked["include_missed"] is not False, (
        "_on_unclear asked for a narrower view of 'open' than interpret was "
        "given - that is the whole bug")


def test_02_two_missed_medicines_get_the_which_one_question(monkeypatch):
    sent, _ = _run_unclear(monkeypatch, _missed_two_medicines())
    assert len(sent) == 1
    body = sent[0]
    assert "Panadol 500mg" in body and "polymalt syrup" in body, body


def test_03_it_never_claims_not_to_have_understood_her(monkeypatch):
    """She was perfectly clear. Saying otherwise is what made her repeat it."""
    sent, _ = _run_unclear(monkeypatch, _missed_two_medicines())
    assert "samajh nahi aaya" not in sent[0].lower(), sent[0]


def test_04_the_prompt_placeholder_never_reaches_a_patient(monkeypatch):
    """The exact sentence she was sent four times."""
    sent, _ = _run_unclear(monkeypatch, _missed_two_medicines())
    assert "apni dawai" not in sent[0].lower(), sent[0]


# ==========================================================================
# one missed medicine is not a question - it is a late confirmation
# ==========================================================================


def test_05_a_single_missed_dose_resolves_instead_of_asking():
    one = [Dose("d1", "panadol", "MISSED", "Panadol 500mg")]
    dose_id, ambiguous = resolve_dose("le li hai", None, one)
    assert dose_id == "d1" and ambiguous is False


def test_06_several_missed_doses_of_one_medicine_are_not_a_question():
    same = [Dose("d1", "panadol", "MISSED", "Panadol 500mg"),
            Dose("d2", "panadol", "MISSED", "Panadol 500mg")]
    _, ambiguous = resolve_dose("le li hai", None, same)
    assert ambiguous is False


def test_07_naming_the_medicine_still_settles_it():
    dose_id, ambiguous = resolve_dose("polymalt le li", None,
                                      _missed_two_medicines())
    assert dose_id == "d2" and ambiguous is False


# ==========================================================================
# and an awaiting dose still wins over a missed one
# ==========================================================================


def test_08_an_awaiting_dose_is_not_crowded_out_by_a_missed_one():
    mixed = [Dose("d1", "panadol", "MISSED", "Panadol 500mg"),
             Dose("d2", "polymalt", "AWAITING_REPLY", "polymalt syrup")]
    dose_id, ambiguous = resolve_dose("le li hai", None, mixed)
    assert dose_id == "d2" and ambiguous is False, (
        "a missed dose must not make a live one ambiguous")


def test_09_with_nothing_open_at_all_it_still_answers_politely(monkeypatch):
    sent, _ = _run_unclear(monkeypatch, [], worded=None)
    assert len(sent) == 1 and sent[0].strip()
