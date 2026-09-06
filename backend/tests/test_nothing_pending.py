"""Understanding somebody and having something to record are different things.

Maani ji's Panadol was a one-day course. It completed. Her reminders were also
stopped. So when she said "mene dawai kha li hai" - three times by voice, and
then "I have taken the medicine" in plain English - there was no dose anywhere
for the answer to land on.

She was told, every single time:

    "Maaf kijiye, samajh nahi aaya. Kya aap ne apni dawai le li hai?"

Nothing had failed to understand her. There was simply nothing pending. But
"samajh nahi aaya" claims the first when only the second is true, so she kept
rephrasing - into Urdu, into English, by voice, by text - and there was no
sentence she could have sent that would have worked. Seen on a real phone,
2026-09-06.

Worse, the reply before it promised "thori der mein dobara yaad dila denge" on
a course that had already finished and with reminders stopped. That is a plain
untruth, and it is what made an empty schedule look like a broken ear.

    pytest backend/tests/test_nothing_pending.py -v
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import respond  # noqa: E402
from app.agent.interpret import Intent  # noqa: E402


class Patient:
    id = "p1"
    name = "Maani"
    language = "ur"
    whatsapp_number = "923001234567"


class Dose:
    def __init__(self, id="d1", medicine="panadol", state="AWAITING_REPLY"):
        self.id = id
        self.medicine_name = medicine
        self.medicine_label = "Panadol 500mg"
        self.state = state


def _intent(kind, text, dose_id=None):
    return Intent(kind=kind, dose_id=dose_id, reason=text, confidence=0.9,
                  medicine=None, text=text, forwarded=False, ambiguous=False)


def _drive(monkeypatch, handler, intent, doses):
    """Run one respond handler, capturing what it would have said."""
    sent: list[str] = []

    async def fake_send(patient, draft, **_kw):
        sent.append(draft)

    async def fake_chat(*_a, **_k):
        return None

    monkeypatch.setattr(respond, "open_doses_for", lambda *_a, **_k: list(doses))
    monkeypatch.setattr(respond, "_send_checked", fake_send)
    monkeypatch.setattr(respond.wa, "send_text", fake_send)
    monkeypatch.setattr(respond.llm, "try_chat", fake_chat)

    asyncio.run(handler(intent, Patient(), "ur", [], "Usman", []))
    return sent


# ==========================================================================
# the sentence she actually sent, with the schedule she actually had
# ==========================================================================


def test_01_taken_with_nothing_pending_does_not_claim_confusion(monkeypatch):
    sent = _drive(monkeypatch, respond._on_taken,
                  _intent("taken", "mene dawai kha li hai"), [])
    assert len(sent) == 1
    assert "samajh nahi aaya" not in sent[0].lower(), sent[0]


def test_02_it_says_plainly_that_nothing_was_pending(monkeypatch):
    sent = _drive(monkeypatch, respond._on_taken,
                  _intent("taken", "I have taken the medicine"), [])
    assert "baaki nahi thi" in sent[0].lower(), sent[0]


def test_03_it_thanks_her_by_name(monkeypatch):
    sent = _drive(monkeypatch, respond._on_taken,
                  _intent("taken", "le li hai"), [])
    assert "Maani" in sent[0], sent[0]


def test_04_the_prompt_placeholder_cannot_appear(monkeypatch):
    """The exact wording she was sent four times."""
    sent = _drive(monkeypatch, respond._on_taken,
                  _intent("taken", "le li hai"), [])
    assert "apni dawai le li hai" not in sent[0].lower(), sent[0]


# ==========================================================================
# and we stop promising reminders that are never coming
# ==========================================================================


def test_05_later_does_not_promise_a_reminder_that_cannot_come(monkeypatch):
    sent = _drive(monkeypatch, respond._on_later,
                  _intent("later", "abhi nahi"), [])
    assert "yaad dila denge" not in sent[0].lower(), sent[0]
    assert "baaki nahi thi" in sent[0].lower(), sent[0]


def test_06_not_taken_with_nothing_pending_says_the_same(monkeypatch):
    sent = _drive(monkeypatch, respond._on_not_taken,
                  _intent("not_taken", "nahi li"), [])
    assert "baaki nahi thi" in sent[0].lower(), sent[0]


# ==========================================================================
# none of which may change what happens when a dose IS open
# ==========================================================================


def test_07_later_still_acknowledges_a_real_open_dose(monkeypatch):
    monkeypatch.setattr(respond, "_record_reason", lambda *_a, **_k: None)
    sent = _drive(monkeypatch, respond._on_later,
                  _intent("later", "abhi nahi", dose_id="d1"), [Dose()])
    assert "yaad dila denge" in sent[0].lower(), sent[0]


def test_08_an_open_dose_still_reaches_the_unclear_path(monkeypatch):
    """With a dose open we must still ask, not claim nothing was pending."""
    sent = _drive(monkeypatch, respond._on_taken,
                  _intent("taken", "hmm"), [Dose()])
    assert "baaki nahi thi" not in sent[0].lower(), sent[0]
    assert "Panadol" in sent[0], sent[0]
