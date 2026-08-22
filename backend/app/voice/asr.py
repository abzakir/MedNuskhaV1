"""Speech to text for inbound voice notes.

Two engines, deliberately:

* **Groq `whisper-large-v3`** first. Free tier, and measurably better on Urdu
  than anything that runs on a laptop CPU.
* **`faster-whisper` locally** as the fallback, when the pool is rate-limited
  or the venue's wifi dies. Slower and less accurate, but it has no quota and
  needs no network - which is exactly what you want at 11pm before a demo.

Use `small`, never `base`. Measured 2026-08-22: `base` transcribed
"ابھی نہیں" (*abhi nahi*, "not now") as "اب ہی" (*ab hi*, "right now"),
inverting the meaning of a dose reply.

A transcript is never expected to be perfect. `agent.interpret` reads it with a
language model, not a regex, so "leli hai" still means "I took it" - and
section 11's confidence floor catches the cases where it genuinely does not.
"""

from __future__ import annotations

import asyncio
import logging

from app.agent import llm
from app.config import settings

log = logging.getLogger(__name__)

_model = None


def get_model():
    """Load faster-whisper once per process and cache it.

    The first load downloads weights, so it is warmed at startup rather than
    on the first patient voice note.
    """
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        log.info("loading faster-whisper %r (first run downloads weights)",
                 settings.whisper_model)
        _model = WhisperModel(settings.whisper_model, device="cpu",
                              compute_type="int8")
        log.info("faster-whisper ready")
    return _model


async def warm_up() -> None:
    """Preload the local model so the fallback is instant when it is needed."""
    try:
        await asyncio.to_thread(get_model)
    except Exception as exc:  # noqa: BLE001 - the cloud path still works
        log.warning("could not warm the local ASR model: %s", exc)


def _transcribe_local(audio: bytes, language: str) -> str:
    import io

    segments, _info = get_model().transcribe(
        io.BytesIO(audio), language=language, beam_size=5, vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


async def transcribe(audio: bytes, language: str = "ur") -> str:
    """Transcribe a voice note. Returns "" if nothing could be made of it.

    Never raises: a failed transcription becomes an empty string, which
    `interpret` turns into `unclear`, which asks the patient one short
    question. That is a far better outcome than an exception swallowing a
    reply.
    """
    if not audio:
        return ""

    try:
        text = await llm.transcribe(audio, filename="voice.ogg", language=language)
        if text:
            log.info("transcribed %d bytes via Groq: %r", len(audio), text[:80])
            return text
        log.warning("Groq returned an empty transcript - trying locally")
    except Exception as exc:  # noqa: BLE001 - fall through to the local model
        log.warning("cloud transcription unavailable (%s) - using local model", exc)

    try:
        text = await asyncio.to_thread(_transcribe_local, audio, language)
        log.info("transcribed %d bytes locally: %r", len(audio), text[:80])
        return text
    except Exception as exc:  # noqa: BLE001
        log.error("local transcription failed too: %s", exc)
        return ""
