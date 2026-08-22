"""Google Cloud Text-to-Speech, ur-PK voices.

Invariant 7: output is OGG/Opus. Anything else renders as a file attachment
and elderly users will not open it.

Principle 3.4: voice notes are PRE-GENERATED. TTS runs when a schedule is
confirmed, uploads to Supabase Storage under voice-notes/, and the reminder
attaches the existing file. Never synthesise inline in the reminder path.

Cache by (medicine, dose_time) - one file per unique dose text, not per event,
or the free-tier quota is gone before the demo (section 17).

Kill switch (Phase 5): if Google TTS Urdu is unusable by 18:00 on Day 3,
switch to Piper (ur_PK ONNX voice) and log the swap. Do not swap silently.
"""

from __future__ import annotations

_PHASE = "Phase 5 - voice"


def pick_voice() -> str:
    """Call list_voices and return the highest-quality ur-PK voice available.

    Do not hardcode a voice name from memory - the available Neural2 and
    Chirp3-HD ur-PK voices change.
    """
    raise NotImplementedError(_PHASE)


async def synthesise(text: str, language: str = "ur") -> bytes:
    """Render text to OGG/Opus audio bytes."""
    raise NotImplementedError(_PHASE)


async def pregenerate_for_schedule(schedule_id: str) -> int:
    """Generate and upload one voice note per unique dose text on a schedule.

    Runs as a background task when a caretaker confirms the schedule. Writes
    the storage key onto each dose_event. Returns the number of files created
    (0 when everything was already cached).
    """
    raise NotImplementedError(_PHASE)
