"""Prescription photo -> structured medicine list, via Qwen-VL (DashScope).

Phase 7, stretch. Manual entry stays the reliable demo path.

Invariant 3.3, no exceptions - not in dev, not for the demo: extraction is a
DRAFT. A schedule is only ever activated after a caretaker reviews the
extracted list on a confirmation screen and presses Confirm.
"""

from __future__ import annotations

_PHASE = "Phase 7 - prescription OCR (stretch)"


async def extract(image: bytes) -> dict:
    """Send the image to Qwen-VL with a structured-output prompt.

    Requests a JSON list of {name, strength, form, dose_times, food_rule,
    duration_days}. The raw response is stored on prescription.raw_extraction
    before any parsing, so a bad extraction is debuggable rather than lost.
    """
    raise NotImplementedError(_PHASE)
