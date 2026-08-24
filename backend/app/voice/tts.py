"""Urdu text to an OGG/Opus voice note, via edge-tts.

Replaced Google Cloud TTS on 2026-08-22 because that wanted a card on file.
`edge-tts` reaches the same Microsoft neural voices with no account, no card
and no API key. Voice is `TTS_VOICE`, default `ur-PK-UzmaNeural`.

Invariant 7: output is OGG/Opus, mono. Anything else renders in WhatsApp as a
file attachment, and an elderly user will not tap it. edge-tts returns MP3, so
PyAV does the conversion - it is already present as a faster-whisper
dependency, so no ffmpeg binary is needed here or on the ECS box.

Principle 3.4: voice notes are PRE-GENERATED. Synthesis runs when a caretaker
confirms a schedule, and the reminder attaches the finished file. Nothing in
the reminder path ever calls out to Microsoft.

**The spoken text is Urdu script, not the Roman Urdu of the message.** Measured
2026-08-23 by synthesising both and transcribing them back: given Roman Urdu,
this voice drops the patient's name and turns "waqt hai" into "ہائی". See
`i18n/strings.SPOKEN`, which is where the spoken copy lives and why.

Kill switch: set `VOICE_NOTES_ENABLED=false` and reminders go back to text
only, with no code change. The section 14 fallback if edge-tts is blocked or
the venue has no internet is Piper (ur_PK ONNX) - not wired, and a deliberate
choice to make rather than a silent swap.
"""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import timezone

import av
import edge_tts
from sqlmodel import col, select

from app.config import settings
from app.db import session_scope
from app.i18n import strings
from app.models import DoseEvent, Medicine, Schedule
from app.voice import store

log = logging.getLogger(__name__)

#: WhatsApp voice notes are mono; 48kHz is what Opus wants natively.
SAMPLE_RATE = 48000


class SynthesisFailed(RuntimeError):
    """edge-tts produced nothing usable for this text."""


# --------------------------------------------------------------------------
# synthesis
# --------------------------------------------------------------------------


async def _mp3(text: str, voice: str) -> bytes:
    buf = bytearray()
    async for chunk in edge_tts.Communicate(text, voice).stream():
        if chunk["type"] == "audio":
            buf.extend(chunk["data"])
    return bytes(buf)


def to_ogg_opus(mp3: bytes) -> bytes:
    """MP3 -> OGG/Opus mono. About 0.2s, and no ffmpeg binary involved."""
    source = av.open(io.BytesIO(mp3), "r")
    out = io.BytesIO()
    target = av.open(out, "w", format="ogg")
    try:
        stream = target.add_stream("libopus", rate=SAMPLE_RATE)
        stream.layout = "mono"
        resampler = av.AudioResampler(format="s16", layout="mono",
                                      rate=SAMPLE_RATE)
        for frame in source.decode(audio=0):
            for resampled in resampler.resample(frame):
                for packet in stream.encode(resampled):
                    target.mux(packet)
        for packet in stream.encode(None):
            target.mux(packet)
    finally:
        target.close()
        source.close()
    return out.getvalue()


async def synthesise(text: str, language: str = "ur") -> bytes:
    """Render one sentence to OGG/Opus bytes.

    `language` is accepted for the section 9 contract and to pick the voice;
    the text itself must already be in the script that voice reads.
    """
    clean = " ".join((text or "").split())
    if not clean:
        raise SynthesisFailed("nothing to say")

    voice = settings.tts_voice
    try:
        mp3 = await _mp3(clean, voice)
    except edge_tts.exceptions.NoAudioReceived as exc:
        # Real and reachable: this voice returns NO audio at all for text it
        # cannot read - a bare Latin word, for instance. Better a text-only
        # reminder than an exception inside a background task.
        raise SynthesisFailed(
            f"{voice} returned no audio for {clean[:60]!r}") from exc

    if not mp3:
        raise SynthesisFailed(f"{voice} returned an empty stream")

    ogg = await asyncio.to_thread(to_ogg_opus, mp3)
    if not ogg:
        raise SynthesisFailed("conversion to OGG/Opus produced nothing")
    return ogg


async def ensure_cached(text: str) -> str | None:
    """Make sure a sentence has audio on disk. Returns its key, or None.

    Idempotent and safe to call repeatedly - the whole point of the
    content-addressed key is that the second call is a `stat()`.
    """
    clean = " ".join((text or "").split())
    if not clean:
        return None

    key = store.key_for(clean)
    if store.has_local(key):
        return key
    if store.get(key) is not None:      # already archived, now pulled local
        return key

    try:
        blob = await synthesise(clean)
    except SynthesisFailed as exc:
        log.warning("no voice note for %r: %s", clean[:60], exc)
        return None
    except Exception as exc:  # noqa: BLE001 - never break the caller
        log.error("synthesis failed for %r: %s", clean[:60], exc)
        return None

    await asyncio.to_thread(store.put, key, blob)
    log.info("generated voice note %s (%d bytes) for %r",
             key, len(blob), clean[:60])
    return key


# --------------------------------------------------------------------------
# pre-generation, when a schedule is confirmed
# --------------------------------------------------------------------------


def _spoken_lines(session, schedule: Schedule) -> dict[str, str]:
    """The sentences this schedule will ever need, keyed by dose time.

    One per unique dose time, not one per dose: a 14-day course at 08:00 and
    20:00 is two sentences, not twenty-eight.
    """
    medicine = session.get(Medicine, schedule.medicine_id)
    if medicine is None:
        return {}

    label = medicine.name
    if medicine.strength:
        label = f"{medicine.name} {medicine.strength}"

    lines: dict[str, str] = {}
    for hhmm in schedule.dose_times or []:
        try:
            hour24 = int(hhmm.split(":")[0])
        except (ValueError, IndexError):
            log.warning("schedule %s has an odd dose time %r",
                        schedule.id, hhmm)
            continue
        # 12-hour, the way it is said aloud, plus the part-of-day word that
        # keeps the 08:00 and 20:00 doses from being the same sentence.
        line = strings.spoken("dose_reminder",
                              period=strings.period_word(hour24),
                              hour=str(hour24 % 12 or 12),
                              medicine=label)
        if line:
            lines[hhmm] = line
    return lines


def _plan(schedule_id: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """(sentence per dose time, [(dose_id, dose time)]) for one schedule."""
    with session_scope() as session:
        schedule = session.get(Schedule, schedule_id)
        if schedule is None:
            return {}, []
        lines = _spoken_lines(session, schedule)

        doses = session.exec(
            select(DoseEvent)
            .where(DoseEvent.schedule_id == schedule_id)
            .order_by(col(DoseEvent.scheduled_at))
        ).all()

        pairs = []
        for dose in doses:
            when = dose.scheduled_at
            if when.tzinfo is None:
                # Postgres can hand these back naive; they are always UTC.
                when = when.replace(tzinfo=timezone.utc)
            pairs.append((dose.id, when.astimezone(settings.tz).strftime("%H:%M")))
        return lines, pairs


def _attach(assignments: dict[str, str]) -> int:
    """Write voice_note_key onto each dose. Returns how many changed."""
    if not assignments:
        return 0
    changed = 0
    with session_scope() as session:
        for dose_id, key in assignments.items():
            dose = session.get(DoseEvent, dose_id)
            if dose is None or dose.voice_note_key == key:
                continue
            dose.voice_note_key = key
            session.add(dose)
            changed += 1
        session.commit()
    return changed


async def pregenerate_for_schedule(schedule_id: str) -> int:
    """Generate one voice note per unique dose text and attach it to the doses.

    Runs as a background task when a caretaker confirms a schedule. Returns the
    number of audio files created - 0 means everything was already cached,
    which is the normal case on the second call.
    """
    if not settings.voice_notes_enabled:
        log.info("voice notes disabled - skipping pre-generation")
        return 0

    lines, pairs = await asyncio.to_thread(_plan, schedule_id)
    if not lines:
        log.info("schedule %s has nothing to say", schedule_id)
        return 0

    created = 0
    keys: dict[str, str] = {}
    for hhmm, sentence in lines.items():
        existed = store.has_local(store.key_for(sentence))
        key = await ensure_cached(sentence)
        if key:
            keys[hhmm] = key
            if not existed:
                created += 1

    assignments = {dose_id: keys[hhmm]
                   for dose_id, hhmm in pairs if hhmm in keys}
    attached = await asyncio.to_thread(_attach, assignments)

    log.info("schedule %s: %d voice note(s) created, %d dose(s) attached",
             schedule_id, created, attached)
    return created


async def pregenerate_for_medicine(medicine_id: str) -> int:
    """Every active schedule for one medicine. What the API calls."""
    with session_scope() as session:
        schedule_ids = list(session.exec(
            select(Schedule.id).where(Schedule.medicine_id == medicine_id)
        ).all())

    total = 0
    for schedule_id in schedule_ids:
        total += await pregenerate_for_schedule(schedule_id)
    return total


def audio_for(dose_id: str) -> bytes | None:
    """The pre-generated audio for one dose, or None.

    Called from the reminder path, so it reads and never synthesises. A miss
    means the dose goes out as text alone.
    """
    if not settings.voice_notes_enabled:
        return None
    with session_scope() as session:
        dose = session.get(DoseEvent, dose_id)
        key = dose.voice_note_key if dose else None
    return store.get(key) if key else None


def pick_voice() -> str:
    """The configured voice.

    Kept from the section 9 contract. It no longer queries a provider for a
    voice list: there are exactly two Pakistani Urdu voices on this stack,
    `ur-PK-UzmaNeural` and `ur-PK-AsadNeural`, and which one speaks to a
    patient is a decision the team made by ear rather than something to
    rediscover at runtime.
    """
    return settings.tts_voice
