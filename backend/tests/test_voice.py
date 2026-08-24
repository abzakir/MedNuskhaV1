"""Spoken copy and the voice-note cache key, with no network and no database.

The integration side - real synthesis, real audio, the reminder path - is
`scripts/verify/verify_voice.py`. What is pinned here is the reasoning that
would break quietly: which sentences are allowed to be spoken at all, and what
makes two of them the same file.
"""

from __future__ import annotations

import pytest

from app.i18n import strings
from app.voice import store


def reminder(hour24: int, medicine: str = "Panadol 500mg") -> str:
    return strings.spoken("dose_reminder",
                          period=strings.period_word(hour24),
                          hour=str(hour24 % 12 or 12),
                          medicine=medicine)


# --------------------------------------------------------------------------
# what may be spoken
# --------------------------------------------------------------------------


def test_the_reminder_has_a_spoken_form():
    assert reminder(8)


def test_spoken_copy_is_urdu_script_not_roman():
    """Measured: given Roman Urdu this voice drops words. See strings.SPOKEN."""
    line = reminder(8)
    assert any("؀" <= c <= "ۿ" for c in line)


def test_the_medicine_name_is_left_exactly_as_stored():
    """Transliterating a drug name ourselves would be inventing a spelling."""
    assert "Panadol 500mg" in reminder(8)


def test_the_spoken_reminder_does_not_lead_with_the_patient_name():
    """A Latin name at the start of an Urdu sentence is swallowed by the voice."""
    assert "{name}" not in strings.SPOKEN["dose_reminder"]


def test_free_text_from_the_database_is_never_spoken():
    """medicine_info interpolates a caretaker-typed purpose in Roman Urdu.

    Spoken, "bukhar aur dard ke liye" loses "bukhar" outright - a voice note
    that drops what a medicine treats is worse than one that never plays.
    """
    assert strings.spoken("medicine_info", medicine="Panadol",
                          purpose="bukhar ke liye", food_rule="") is None


def test_an_unknown_key_has_no_spoken_form_rather_than_raising():
    assert strings.spoken("no_such_string_at_all") is None


def test_every_spoken_key_also_exists_as_text():
    """Nothing may be speakable but unreadable - the text is the fallback."""
    assert set(strings.SPOKEN) <= set(strings.STRINGS)


# --------------------------------------------------------------------------
# part of day
# --------------------------------------------------------------------------


@pytest.mark.parametrize("hour24,word", [
    (5, "صبح"), (8, "صبح"), (11, "صبح"),
    (12, "دوپہر"), (15, "دوپہر"),
    (16, "شام"), (18, "شام"),
    (19, "رات"), (22, "رات"), (0, "رات"), (3, "رات"),
])
def test_period_word(hour24, word):
    assert strings.period_word(hour24) == word


def test_morning_and_evening_are_not_the_same_sentence():
    """Without the part-of-day word, 08:00 and 20:00 both read "8 baj gaye".

    They then share one cache file and an evening dose sounds like a morning
    one. This is the check that caught it.
    """
    assert reminder(8) != reminder(20)
    assert strings.period_word(8) in reminder(8)
    assert strings.period_word(20) in reminder(20)


# --------------------------------------------------------------------------
# the cache key
# --------------------------------------------------------------------------


def test_the_key_is_the_content():
    assert store.key_for("ایک دو تین") == store.key_for("ایک دو تین")


def test_whitespace_does_not_make_a_second_file():
    assert store.key_for("  ایک   دو  ") == store.key_for("ایک دو")


def test_a_different_sentence_makes_a_different_file():
    assert reminder(8) != reminder(9)
    assert store.key_for(reminder(8)) != store.key_for(reminder(9))


def test_a_different_medicine_makes_a_different_file():
    assert store.key_for(reminder(8)) != store.key_for(reminder(8, "Brufen 400mg"))


def test_a_different_voice_makes_a_different_file():
    """Changing TTS_VOICE must not serve audio in the previous voice."""
    assert store.key_for("ایک", voice="ur-PK-UzmaNeural") \
        != store.key_for("ایک", voice="ur-PK-AsadNeural")


def test_the_key_looks_like_an_ogg_file():
    key = store.key_for(reminder(8))
    assert key.endswith(".ogg")
    assert len(key) == store.KEY_CHARS + len(".ogg")
