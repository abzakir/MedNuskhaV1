"""Report arithmetic and share tokens, with no database and no services.

The integration side - real doses, real PDFs, the daily job - is
`scripts/verify/verify_reports.py`. What is pinned here is the reasoning that
would be easy to break silently later: which doses count towards adherence,
what a streak is, which dose time is "hardest", and that a share token cannot
be reused across reports.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.reports import storage
from app.reports.data import (DECIDED_STATES, TAKEN_STATES, CourseReport,
                              MissedDose, TimeOfDay, _streaks)


def course(**kwargs) -> CourseReport:
    base = dict(
        patient_name="Zubaida",
        medicine_label="Panadol 500mg",
        start_date=date(2026, 8, 8),
        end_date=date(2026, 8, 21),
        duration_days=14,
        dose_times=["08:00", "20:00"],
    )
    base.update(kwargs)
    return CourseReport(**base)


# --------------------------------------------------------------------------
# adherence
# --------------------------------------------------------------------------


def test_adherence_is_over_settled_doses_only():
    """A dose due this evening must not count against the patient.

    This is the difference between a report that says 82% and one that says
    58% for the same fortnight, purely because it was generated at breakfast.
    """
    c = course(on_time=19, late=4, missed=4, skipped=1, pending=6)
    assert c.taken == 23
    assert c.decided == 28
    assert c.scheduled == 34
    assert c.percent == 82


def test_pending_doses_do_not_move_the_percentage():
    settled = course(on_time=10, missed=2)
    with_pending = course(on_time=10, missed=2, pending=9)
    assert settled.percent == with_pending.percent


def test_no_settled_dose_gives_no_percentage_rather_than_zero():
    """0% would read as "took nothing". None makes the report say so in words."""
    c = course(pending=8)
    assert c.decided == 0
    assert c.percent is None


def test_a_late_dose_still_counts_as_taken():
    assert course(late=4).taken == 4
    assert course(on_time=0, late=4).percent == 100


def test_declined_doses_count_against_adherence_but_are_not_missed():
    c = course(on_time=9, skipped=1)
    assert c.missed == 0
    assert c.decided == 10
    assert c.percent == 90


def test_state_groups_agree_with_each_other():
    assert set(TAKEN_STATES) <= set(DECIDED_STATES)
    assert "SCHEDULED" not in DECIDED_STATES
    assert "AWAITING_REPLY" not in DECIDED_STATES


# --------------------------------------------------------------------------
# streaks
# --------------------------------------------------------------------------


def test_streaks_finds_the_longest_and_the_trailing_run():
    states = ["TAKEN", "TAKEN", "MISSED", "TAKEN", "TAKEN", "TAKEN", "TAKEN"]
    assert _streaks(states) == (4, 4)


def test_a_streak_broken_at_the_end_still_reports_the_best():
    states = ["TAKEN"] * 5 + ["MISSED"]
    assert _streaks(states) == (5, 0)


def test_an_unanswered_dose_neither_extends_nor_breaks_a_streak():
    """Silence is not a failure yet - the follow-up may still land."""
    assert _streaks(["TAKEN", "AWAITING_REPLY", "TAKEN"]) == (2, 2)


def test_a_late_dose_keeps_the_streak_alive():
    assert _streaks(["TAKEN", "TAKEN_LATE", "TAKEN"]) == (3, 3)


def test_no_doses_is_no_streak():
    assert _streaks([]) == (0, 0)


# --------------------------------------------------------------------------
# hardest time of day
# --------------------------------------------------------------------------


def test_hardest_time_is_the_one_missed_most():
    c = course(by_time=[TimeOfDay("08:00", 12, 2), TimeOfDay("20:00", 11, 3)])
    assert c.hardest_time.hhmm == "20:00"


def test_hardest_time_is_none_when_nothing_was_missed():
    """The caretaker report must not invent a problem to talk about."""
    c = course(by_time=[TimeOfDay("08:00", 14, 0), TimeOfDay("20:00", 14, 0)])
    assert c.hardest_time is None


def test_a_tie_is_broken_by_the_earlier_time_not_at_random():
    c = course(by_time=[TimeOfDay("20:00", 10, 3), TimeOfDay("08:00", 10, 3)])
    assert c.hardest_time.hhmm == "08:00"


def test_time_of_day_percentage_ignores_unanswered_doses():
    slot = TimeOfDay("08:00", taken=3, missed=1)
    assert slot.decided == 4
    assert slot.percent == 75
    assert TimeOfDay("08:00", 0, 0).percent is None


# --------------------------------------------------------------------------
# completeness
# --------------------------------------------------------------------------


def test_a_course_with_nothing_pending_is_complete():
    assert course(on_time=28).is_complete
    assert not course(on_time=27, pending=1).is_complete


def test_a_missed_dose_with_no_words_is_still_a_missed_dose():
    """A silent miss must appear in the doctor's log, not vanish from it."""
    entry = MissedDose(when=datetime(2026, 8, 14, 8, tzinfo=timezone.utc),
                       state="MISSED")
    assert entry.said == ""


# --------------------------------------------------------------------------
# share tokens
# --------------------------------------------------------------------------


def test_a_share_token_is_stable_for_the_same_report():
    assert storage.share_token("abc") == storage.share_token("abc")


def test_a_share_token_does_not_open_another_report():
    """The link is the only guard on an unauthenticated medical document."""
    assert not storage.token_ok("report-a", storage.share_token("report-b"))


def test_a_report_accepts_its_own_token():
    assert storage.token_ok("report-a", storage.share_token("report-a"))


@pytest.mark.parametrize("bad", ["", "   ", "0" * 32, "not-a-token"])
def test_a_wrong_token_is_refused(bad):
    assert not storage.token_ok("report-a", bad)


def test_the_object_key_is_namespaced_by_patient():
    key = storage.object_key("patient-1", "report-9")
    assert key.startswith("patient-1/")
    assert key.endswith(".pdf")
