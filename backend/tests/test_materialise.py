"""Which dose times get a row, and which are refused.

The rule being pinned: **the agent is answerable for a medicine from the
moment it is added, never retroactively.**

Adding a medicine at 2pm with a morning dose used to create an 08:00 row for
today, which the very next tick wrote straight to MISSED - reporting a dose
missed five hours before the medicine existed, and dragging the patient's
adherence down for something nobody was ever asked. Reported from a real
dashboard, 2026-08-30.

Pure: `to_utc` and the window arithmetic are the whole of the decision, so
there is no database here.

    pytest backend/tests/test_materialise.py -v
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.scheduler import ticker  # noqa: E402


@pytest.fixture
def at_2pm(monkeypatch):
    """Freeze the clock at 14:00 Karachi, the hour in the bug report."""
    now = datetime(2026, 8, 30, 14, 0, tzinfo=settings.tz).astimezone(timezone.utc)
    monkeypatch.setattr(ticker, "_now", lambda: now)
    return now


def _would_create(hhmm: str, day=None) -> bool:
    """Whether materialisation would make a row for this local dose time."""
    day = day or ticker.local_today()
    when = ticker.to_utc(day, hhmm)
    return ticker._remindable_from() <= when <= ticker._now() + timedelta(hours=24)


# ==========================================================================
# the report: added at 2pm, morning dose
# ==========================================================================


def test_01_a_morning_dose_added_in_the_afternoon_is_not_created(at_2pm):
    """The whole bug, in one line."""
    assert not _would_create("09:00"), \
        "a 09:00 dose added at 14:00 can only ever be recorded as missed"


def test_02_the_evening_dose_of_the_same_medicine_is_created(at_2pm):
    """The other half: the medicine still starts working today."""
    assert _would_create("19:00")
    assert _would_create("21:30")


def test_03_tomorrow_morning_is_created(at_2pm):
    """Refusing today's must not refuse the course."""
    tomorrow = ticker.local_today() + timedelta(days=1)
    assert _would_create("09:00", day=tomorrow)


# ==========================================================================
# the boundary - a dose that IS still worth reminding about
# ==========================================================================


def test_04_a_dose_just_gone_by_is_still_created_and_still_sent(monkeypatch):
    """Added at 08:20 for an 08:00 dose: remind her, she may not have taken it.

    This is the line between "too late to be anything but a black mark" and
    "late but still worth asking", and it is the ticker's own staleness
    window, so the two can never disagree.
    """
    now = datetime(2026, 8, 30, 8, 20, tzinfo=settings.tz).astimezone(timezone.utc)
    monkeypatch.setattr(ticker, "_now", lambda: now)
    assert _would_create("08:00")


def test_05_the_cutoff_is_exactly_the_tickers_stale_window(monkeypatch):
    """A dose created at the boundary must not be stale on the very next tick.

    If these two ever drift apart, adding a medicine starts producing
    instantly-missed doses again - which is precisely the bug.
    """
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(ticker, "_now", lambda: now)

    window = timedelta(minutes=settings.escalate_minutes) + ticker._STALE_GRACE
    assert ticker._remindable_from() == now - window

    oldest_creatable = ticker._remindable_from()
    assert now - oldest_creatable <= window, \
        "the oldest dose we will create must still count as fresh, not stale"


def test_06_nothing_beyond_the_24_hour_horizon(at_2pm):
    """Unchanged behaviour, asserted so the new floor did not remove the ceiling."""
    in_three_days = ticker.local_today() + timedelta(days=3)
    assert not _would_create("09:00", day=in_three_days)
