"""The agent may never name a medicine the patient is not on.

On 2026-08-30 a patient taking polymalt was asked "Kya aap ne Panadol le li
hai?". The name came out of a worked example inside the clarifying prompt -
the model copied the example instead of substituting her medicine - and
nothing downstream noticed, because the sentence carried no dose figure and
broke no clinical rule. It simply named the wrong drug to someone who might
have gone and taken it.

Three things are pinned here, in the order they now fire:

  1. the prompt carries no drug name for a model to reach for
  2. a clarifying question that names none of the medicines we offered is
     dropped in favour of the canned string
  3. the guardrail refuses any outbound text naming a medicine that is not
     this patient's - the layer that does not depend on a prompt behaving

    pytest backend/tests/test_medicine_naming.py -v
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import guardrails, respond  # noqa: E402


class Dose:
    def __init__(self, name: str, label: str | None = None):
        self.id = f"dose-{name}"
        self.medicine_name = name
        self.medicine_label = label or name
        self.state = "AWAITING_REPLY"


# ==========================================================================
# 1. the prompt itself
# ==========================================================================


@pytest.mark.parametrize("lang", ["ur", "en"])
def test_01_no_real_drug_name_in_the_prompt_example(lang):
    """A worked example naming a real drug is a name waiting to be copied."""
    example = respond._REGISTER[lang].lower()
    for drug in guardrails.COMMON_MEDICINE_NAMES:
        assert drug not in example, (
            f"{drug!r} is in the {lang} clarify example - a model will copy it")


@pytest.mark.parametrize("lang", ["ur", "en"])
def test_02_the_example_still_shows_where_the_medicine_goes(lang):
    """Removing the drug name must not remove the instruction with it."""
    assert "medicine" in respond._REGISTER[lang].lower()


# ==========================================================================
# 2. checking what the model gives back
# ==========================================================================


def test_03_a_question_naming_the_right_medicine_is_kept(monkeypatch):
    async def worded(*_a, **_k):
        return "Maaf kijiye ga, samajh nahi aaya. Kya aap ne polymalt le li hai?"

    monkeypatch.setattr(respond.llm, "try_chat", worded)
    out = asyncio.run(respond._clarify_text(
        _intent("polymalt le li"), "ur", [Dose("polymalt")]))
    assert out is not None and "polymalt" in out


def test_04_a_question_naming_a_different_medicine_is_thrown_away(monkeypatch):
    """The exact sentence that reached a real patient."""
    async def worded(*_a, **_k):
        return "Maaf kijiye ga, samajh nahi aaya. Kya aap ne Panadol le li hai?"

    monkeypatch.setattr(respond.llm, "try_chat", worded)
    out = asyncio.run(respond._clarify_text(
        _intent("hmm"), "ur", [Dose("polymalt")]))
    assert out is None, "a sentence naming somebody else's medicine must not be sent"


def test_05_with_no_dose_open_the_model_is_not_second_guessed(monkeypatch):
    """Nothing was offered, so naming none of it is not evidence of anything."""
    async def worded(*_a, **_k):
        return "Maaf kijiye ga, samajh nahi aaya. Dobara likh dein?"

    monkeypatch.setattr(respond.llm, "try_chat", worded)
    out = asyncio.run(respond._clarify_text(_intent("hmm"), "ur", []))
    assert out is not None


def test_06_a_dead_model_still_returns_none(monkeypatch):
    async def worded(*_a, **_k):
        return None

    monkeypatch.setattr(respond.llm, "try_chat", worded)
    assert asyncio.run(respond._clarify_text(
        _intent("hmm"), "ur", [Dose("polymalt")])) is None


def test_07_the_label_matches_on_the_name_not_the_strength():
    """"Panadol" counts when the label is "Panadol 500mg"."""
    assert respond._names_one_of("Kya aap ne Panadol le li hai?",
                                 [Dose("Panadol", "Panadol 500mg")])
    assert not respond._names_one_of("Kya aap ne Panadol le li hai?",
                                     [Dose("polymalt", "polymalt syrup")])


# ==========================================================================
# 3. the guardrail behind both of them
# ==========================================================================


def test_08_the_guardrail_blocks_somebody_elses_medicine():
    own = ["polymalt syrup"]
    result = guardrails.check(
        "Maaf kijiye ga, samajh nahi aaya. Kya aap ne Panadol le li hai?",
        known_texts=own)
    assert not result.allowed
    assert result.violated_rule == "foreign_medicine"
    assert result.alert_caretaker, "a caretaker has to hear about this one"
    assert "Panadol" not in result.message


def test_09_the_patients_own_medicine_passes():
    own = ["polymalt syrup"]
    assert guardrails.check("Kya aap ne polymalt le li hai?",
                            known_texts=own).allowed
    assert guardrails.check("Shukriya. polymalt syrup le li - likh liya hai.",
                            known_texts=own).allowed


def test_10_a_patient_on_panadol_may_be_sent_panadol():
    """The check is "not theirs", not "is a drug"."""
    assert guardrails.check("Kya aap ne Panadol le li hai?",
                            known_texts=["Panadol 500mg"]).allowed


def test_11_ordinary_copy_with_no_medicine_in_it_passes():
    for line in ["Maaf kijiye ga, samajh nahi aaya. Dobara likh dein?",
                 "Theek hai. Thori der mein dobara yaad dila denge.",
                 "Shukriya. Likh liya hai."]:
        assert guardrails.check(line, known_texts=["polymalt syrup"]).allowed, line


def test_12_a_name_inside_a_longer_word_is_not_a_mention():
    """Whole words only, or ordinary Urdu starts tripping the check."""
    assert guardrails.names_foreign_medicine(
        "aspirinated", ["polymalt"]) is None


def test_13_the_corpus_grows_with_what_the_system_knows():
    """A medicine nobody seeded, but that another family takes, still counts."""
    assert guardrails.names_foreign_medicine(
        "Kya aap ne Neurobion le li hai?", ["polymalt"]) is None
    assert guardrails.names_foreign_medicine(
        "Kya aap ne Neurobion le li hai?", ["polymalt"],
        known=["Neurobion 5000"]) == "neurobion"


def _intent(text: str):
    from app.agent.interpret import Intent
    return Intent(kind="unclear", dose_id=None, reason=None, confidence=0.0,
                  text=text)
