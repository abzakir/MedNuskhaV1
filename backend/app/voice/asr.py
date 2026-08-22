"""faster-whisper, running locally on CPU. No API key, no quota.

Model comes from WHISPER_MODEL (base, or small for better Urdu). Urdu accuracy
is strong for the short utterances we care about - "le li hai", "abhi nahi".

An inbound audio message is downloaded via whatsapp.client.download_media,
transcribed here, and the text fed into agent.interpret exactly as if the
patient had typed it.
"""

from __future__ import annotations

_PHASE = "Phase 5 - voice"


def get_model():
    """Load the faster-whisper model once per process and cache it.

    First load downloads weights - warm it at startup, not on the first
    patient voice note.
    """
    raise NotImplementedError(_PHASE)


async def transcribe(audio: bytes, language: str = "ur") -> str:
    """Transcribe an audio clip to text."""
    raise NotImplementedError(_PHASE)
