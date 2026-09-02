"""The time a reminder announces must be the dose's own time.

A 09:30 dose was announced as "4 baj gaye" on a real phone, 2026-08-30.

`dose_event.scheduled_at` comes back from Postgres with no tzinfo, and
`.astimezone()` on a naive datetime does NOT assume UTC - it assumes the
machine's local timezone. On the PKT laptop this runs on, the stored 04:30
UTC was read as 04:30 PKT and converted PKT-to-PKT, so the patient was told
the wrong time twice a day.

This is invisible on a UTC server, where the wrong assumption happens to give
the right answer - so the naive case is asserted explicitly here rather than
being left to whichever machine happens to run the suite.

    pytest backend/tests/test_time_label.py -v
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.i18n import strings  # noqa: E402
from app.scheduler.ticker import local_time_label, to_utc  # noqa: E402
from app.whatsapp.client import render  # noqa: E402

DAY = date(2026, 8, 31)


def _as_stored(hhmm: str) -> datetime:
    """The dose exactly as Postgres hands it back: UTC, and naive."""
    return to_utc(DAY, hhmm).replace(tzinfo=None)


# ==========================================================================
# the bug
# ==========================================================================


def test_01_a_naive_timestamp_is_read_as_utc_not_as_local():
    """The whole bug: this returned "4" for a 09:30 dose."""
    assert local_time_label(_as_stored("09:30")) == "9:30"


@pytest.mark.parametrize("hhmm", ["00:00", "06:15", "08:00", "09:30",
                                  "12:00", "13:05", "19:00", "20:00", "23:45"])
def test_02_naive_and_aware_can_never_disagree(hhmm):
    """The two must give the same answer, or the label depends on the host.

    This is the assertion that would have caught it: on a UTC machine both
    paths were right, so only comparing them exposes the difference.
    """
    assert local_time_label(_as_stored(hhmm)) == local_time_label(to_utc(DAY, hhmm))


# ==========================================================================
# what it should say
# ==========================================================================


@pytest.mark.parametrize("hhmm,expected", [
    ("08:00", "8"),        # on the hour: the bare hour, as Urdu says it
    ("20:00", "8"),        # 12-hour - the patient can see whether it is dark
    ("00:00", "12"),
    ("12:00", "12"),
    ("09:30", "9:30"),     # not on the hour: say the actual time
    ("13:05", "1:05"),
    ("23:45", "11:45"),
])
def test_03_the_label_is_the_doses_own_time(hhmm, expected):
    assert local_time_label(_as_stored(hhmm)) == expected


def test_04_a_half_past_dose_is_never_announced_as_the_hour():
    """"9 baj gaye" for a 9:30 dose is telling the patient the wrong time."""
    assert local_time_label(_as_stored("09:30")) != "9"


# ==========================================================================
# the message the patient actually receives
# ==========================================================================


def test_05_the_reminder_names_the_scheduled_time():
    hour = local_time_label(_as_stored("09:30"))
    body = render("dose_reminder", "ur", ["Ammi", hour, "Inderal 10mg", ""])
    assert "9:30 baj gaye" in body
    assert "4 baj gaye" not in body


def test_06_english_does_not_say_oclock_for_a_half_hour():
    """"it's 9:30 o'clock" is not English."""
    body = render("dose_reminder", "en",
                  [ "Ammi", local_time_label(_as_stored("09:30")),
                    "Inderal 10mg", ""])
    assert "9:30" in body
    assert "o'clock" not in body


def test_07_the_caretaker_alert_names_the_same_time():
    """The alert and the reminder must agree about when the dose was."""
    hour = local_time_label(_as_stored("09:30"))
    for lang in ("ur", "en"):
        assert "9:30" in render("caretaker_alert", lang,
                                ["Ammi", hour, "Inderal 10mg"])


def test_08_both_languages_still_exist_for_every_string():
    """The copy edits above must not have dropped a translation."""
    assert strings.missing_translations() == []
