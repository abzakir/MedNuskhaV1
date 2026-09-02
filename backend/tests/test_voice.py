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
    """Nothing may be speakable but unreadable - the text is the fallback.

    A spoken key may be a second WORDING of a message rather than a message of
    its own - `dose_reminder_minutes` is how `dose_reminder` is said for a 9:30
    dose - so it is the message behind the line that has to have text, not the
    line's own key. `SPOKEN_VARIANTS` is where that is declared.
    """
    behind = {strings.text_key_for(k) for k in strings.SPOKEN}
    assert behind <= set(strings.STRINGS)


def test_a_spoken_variant_points_at_a_message_that_exists():
    """A typo in SPOKEN_VARIANTS would otherwise let the check above pass
    while pointing at nothing."""
    for variant, base in strings.SPOKEN_VARIANTS.items():
        assert variant in strings.SPOKEN, f"{variant} is not a spoken key"
        assert base in strings.STRINGS, f"{variant} points at missing {base}"
        assert base in strings.SPOKEN, (
            f"{variant} is a variant of {base}, which must itself be speakable")


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


# --------------------------------------------------------------------------
# does the voice actually SAY the medicine?
# --------------------------------------------------------------------------
#
# `ur-PK-UzmaNeural` silently drops Latin words it cannot transliterate.
# Measured 2026-08-30: "Panadol 500mg", "Inderal 10mg" and "Amlodipine 5mg"
# all come back correctly; "polymalt" is dropped outright and "polymalt syrup"
# keeps only "syrup". A patient was sent "raat ke 10 baj kar 30 minute hue,
# lene ka waqt hai" - time to take, with no idea what.
#
# The real check needs edge-tts and Whisper, so what is pinned here is the
# decision it makes given a transcript, not the transcript itself.

import asyncio  # noqa: E402

from app.voice import tts  # noqa: E402


def _fake_voice(monkeypatch, dropped: set[str]):
    """A voice that silently swallows every word in `dropped`."""
    tts._VERIFIED.clear()

    async def synthesise(text, language="ur"):
        kept = [w for w in text.split() if w.lower() not in dropped]
        return " ".join(kept).encode()

    async def transcribe(audio, language="ur"):
        return audio.decode()

    monkeypatch.setattr(tts, "synthesise", synthesise)
    monkeypatch.setattr("app.voice.asr.transcribe", transcribe)


def _line(medicine: str) -> str:
    return strings.spoken("dose_reminder_minutes", period=strings.period_word(22),
                          hour="10", minute="30", medicine=medicine)


def test_a_medicine_the_voice_can_say_keeps_its_voice_note(monkeypatch):
    _fake_voice(monkeypatch, dropped=set())
    assert asyncio.run(tts.says_the_medicine(_line("Panadol 500mg"),
                                             "Panadol 500mg"))


def test_a_medicine_the_voice_swallows_loses_its_voice_note(monkeypatch):
    """The reported case: the audio never says "polymalt"."""
    _fake_voice(monkeypatch, dropped={"polymalt"})
    assert not asyncio.run(tts.says_the_medicine(_line("polymalt"), "polymalt"))


def test_every_word_of_the_name_has_to_survive_not_just_one(monkeypatch):
    """"polymalt syrup" read aloud as only "syrup" names nothing.

    A house with two syrups in it is exactly the house this product is for.
    """
    _fake_voice(monkeypatch, dropped={"polymalt"})
    assert not asyncio.run(
        tts.says_the_medicine(_line("polymalt syrup"), "polymalt syrup"))


def test_an_unverifiable_sentence_gets_no_voice_note(monkeypatch):
    """The check FAILS CLOSED, and this reverses an earlier decision.

    It first returned True when the transcriber could not be reached, on the
    reasoning that an outage should not silence every patient. What that
    actually did, on 2026-08-30, was let a voice note through saying "raat ke
    10 baj gaye, lene ka waqt hai" - time to take, with no medicine named -
    to a patient with two medicines in the house.

    The two costs are not comparable. A missing voice note leaves a text
    reminder that names the medicine correctly. A nameless voice note is an
    instruction the patient cannot act on.
    """
    tts._VERIFIED.clear()

    async def synthesise(text, language="ur"):
        return b"audio"

    async def transcribe(audio, language="ur"):
        return ""                      # asr.transcribe never raises

    monkeypatch.setattr(tts, "synthesise", synthesise)
    monkeypatch.setattr("app.voice.asr.transcribe", transcribe)
    assert not asyncio.run(tts.says_the_medicine(_line("polymalt"), "polymalt"))


def test_an_inconclusive_answer_is_not_cached(monkeypatch):
    """A transcriber that comes back must be able to change the answer.

    Failing closed would otherwise turn one bad minute into a course with no
    voice notes at all.
    """
    tts._VERIFIED.clear()

    async def synthesise(text, language="ur"):
        return b"audio"

    async def dead(audio, language="ur"):
        return ""

    monkeypatch.setattr(tts, "synthesise", synthesise)
    monkeypatch.setattr("app.voice.asr.transcribe", dead)
    line = _line("Panadol 500mg")
    assert not asyncio.run(tts.says_the_medicine(line, "Panadol 500mg"))
    assert store.key_for(line) not in tts._VERIFIED,         "an outage must not be remembered as a verdict"

    _fake_voice(monkeypatch, dropped=set())
    assert asyncio.run(tts.says_the_medicine(line, "Panadol 500mg"))


def test_a_name_with_nothing_latin_in_it_is_left_alone(monkeypatch):
    """Nothing for the voice to swallow means nothing to check."""
    _fake_voice(monkeypatch, dropped={"anything"})
    assert asyncio.run(tts.says_the_medicine(_line("دوائی"), "دوائی"))


# --------------------------------------------------------------------------
# a dose that did not exist when pre-generation ran
# --------------------------------------------------------------------------
#
# `voice_note_key` is written once, when a caretaker confirms a schedule, and
# can only reach the doses that exist at that moment. Materialisation runs 24
# hours ahead, so every dose from the second day onwards is created later with
# a null key - and silently went out as text. Observed 2026-08-30: a course
# added at 21:57 had audio on that night's dose and none on the next.
#
# The key is the hash of the exact sentence, so a null one is resolved by
# working the sentence out again - a stat(), not a guess, and no synthesis in
# the reminder path (section 3.4).


def test_a_null_key_falls_back_to_the_content_addressed_one(monkeypatch):
    line = "جی، رات - Panadol"
    key = store.key_for(line)

    monkeypatch.setattr(tts, "_sentence_for", lambda _s, _d: line)
    monkeypatch.setattr(store, "get", lambda k: b"ogg" if k == key else None)

    class Dose:
        voice_note_key = None

    monkeypatch.setattr(tts, "session_scope", _one_dose(Dose()))
    assert tts.audio_for("dose-1") == b"ogg"


def test_a_sentence_the_voice_cannot_say_stays_unfound(monkeypatch):
    """The other half: nothing is cached for it, so the fallback finds nothing.

    Removing the file is what stops a rejected sentence coming back to life on
    tomorrow's dose through the very fallback above.
    """
    monkeypatch.setattr(tts, "_sentence_for", lambda _s, _d: "polymalt line")
    monkeypatch.setattr(store, "get", lambda k: None)

    class Dose:
        voice_note_key = None

    monkeypatch.setattr(tts, "session_scope", _one_dose(Dose()))
    assert tts.audio_for("dose-1") is None


def _one_dose(dose):
    """A session_scope() standing in for one dose lookup."""
    class Session:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, _model, _id): return dose
    return lambda: Session()


# --------------------------------------------------------------------------
# every spoken line goes through the same door
# --------------------------------------------------------------------------
#
# The reminder had the swallowed-name check; the follow-up and the spoken
# acknowledgement called ensure_cached directly and did not. So a patient on a
# name the voice drops got a correct text reminder, and then fifteen minutes
# later a voice note saying only "ابھی باقی ہے" - "is still pending" - with no
# idea what was pending.


def test_ensure_spoken_caches_a_name_the_voice_can_say(monkeypatch):
    _fake_voice(monkeypatch, dropped=set())
    saved = {}
    monkeypatch.setattr(store, "put", lambda k, b: saved.__setitem__(k, b))
    monkeypatch.setattr(store, "has_local", lambda k: k in saved)
    monkeypatch.setattr(store, "get", lambda k: saved.get(k))

    key = asyncio.run(tts.ensure_spoken(_line("Panadol 500mg"), "Panadol 500mg"))
    assert key is not None and key in saved


def test_ensure_spoken_refuses_and_stores_nothing(monkeypatch):
    """Nothing may be written for a rejected line - `audio_for` would find it."""
    _fake_voice(monkeypatch, dropped={"polymalt"})
    saved = {}
    forgotten = []
    monkeypatch.setattr(store, "put", lambda k, b: saved.__setitem__(k, b))
    monkeypatch.setattr(store, "has_local", lambda k: k in saved)
    monkeypatch.setattr(store, "get", lambda k: saved.get(k))
    monkeypatch.setattr(store, "forget", forgotten.append)

    assert asyncio.run(tts.ensure_spoken(_line("polymalt"), "polymalt")) is None
    assert not saved, "a rejected sentence must not be cached"
    assert forgotten, "any earlier copy has to be removed too"


def test_ensure_spoken_with_no_medicine_just_caches(monkeypatch):
    """Lines that name no medicine have nothing to check."""
    _fake_voice(monkeypatch, dropped={"polymalt"})
    saved = {}
    monkeypatch.setattr(store, "put", lambda k, b: saved.__setitem__(k, b))
    monkeypatch.setattr(store, "has_local", lambda k: k in saved)
    monkeypatch.setattr(store, "get", lambda k: saved.get(k))

    assert asyncio.run(tts.ensure_spoken("جی، شکریہ۔", None)) is not None


def test_no_caller_bypasses_the_check():
    """ensure_cached is the raw one; nothing that names a medicine may use it.

    A new reply path calling the raw function is exactly how the follow-up and
    the acknowledgement drifted, so this asserts on the source itself.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    for rel in ("backend/app/scheduler/ticker.py", "backend/app/agent/respond.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "ensure_cached(" not in text, (
            f"{rel} calls ensure_cached directly - use ensure_spoken so the "
            f"medicine name is checked")
