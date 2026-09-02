"""Only one process may send reminders, and it must keep proving it.

Section 17 guards the ticker with a Postgres advisory lock. A session-level
advisory lock lives and dies with its connection, and the lock connection is
held open outside the pool with no `pool_pre_ping` - so Supabase's pooler
closing it after an idle spell releases the lock silently while the scheduler
keeps ticking.

Observed on 2026-08-30: the machine slept from 15:10 to 19:41, and on waking
`pg_locks` held no advisory lock at all while this backend was still running
its minute tick. A second backend started at that point - a teammate, or the
same person running dev.ps1 again - would have taken the free lock and every
patient would have been reminded twice.

So the lock is re-checked on every tick rather than trusted from startup.

    pytest backend/tests/test_scheduler_lock.py -v
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.scheduler import ticker  # noqa: E402


class DeadConn:
    """A lock connection whose socket has gone, the way the pooler leaves it."""

    def __init__(self):
        self.closed = False

    def execute(self, *_a, **_k):
        raise OSError("server closed the connection unexpectedly")

    def commit(self):
        raise OSError("server closed the connection unexpectedly")

    def close(self):
        self.closed = True


class LiveConn:
    def __init__(self):
        self.pings = 0
        self.commits = 0

    def execute(self, *_a, **_k):
        self.pings += 1
        return None

    def commit(self):
        self.commits += 1

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _no_real_lock(monkeypatch):
    """Never touch a real database from these."""
    monkeypatch.setattr(ticker, "_lock_conn", None, raising=False)
    yield
    monkeypatch.setattr(ticker, "_lock_conn", None, raising=False)


def test_01_a_live_lock_is_simply_confirmed(monkeypatch):
    live = LiveConn()
    monkeypatch.setattr(ticker, "_lock_conn", live)
    monkeypatch.setattr(ticker, "_acquire_lock",
                        lambda: pytest.fail("must not re-take a lock it holds"))

    assert ticker._holds_lock() is True
    assert live.pings == 1, "the connection has to actually be proven alive"
    assert live.commits == 1, (
        "the ping must COMMIT - an uncommitted one leaves the connection "
        "'idle in transaction', which Supabase's pooler reaps within minutes, "
        "so the check would cause the very drop it is looking for")


def test_02_a_dead_connection_is_noticed_and_the_lock_retaken(monkeypatch):
    """The bug: this used to go unnoticed and the ticker sent anyway."""
    dead = DeadConn()
    monkeypatch.setattr(ticker, "_lock_conn", dead)
    monkeypatch.setattr(ticker, "_acquire_lock", lambda: True)

    assert ticker._holds_lock() is True
    assert dead.closed, "the dead connection must be closed, not leaked"


def test_03_standing_down_when_somebody_else_took_it(monkeypatch):
    """Two backends, one lock. The one that lost it must go quiet."""
    dead = DeadConn()
    monkeypatch.setattr(ticker, "_lock_conn", dead)
    monkeypatch.setattr(ticker, "_acquire_lock", lambda: False)

    assert ticker._holds_lock() is False


def test_04_a_tick_without_the_lock_sends_nothing(monkeypatch):
    """The guard has to sit in front of the work, not beside it."""
    monkeypatch.setattr(ticker, "_holds_lock", lambda: False)
    monkeypatch.setattr(ticker, "materialise_doses",
                        lambda *a, **k: pytest.fail("materialised without the lock"))
    monkeypatch.setattr(ticker, "_due_reminders",
                        lambda: pytest.fail("reminded without the lock"))

    counts = asyncio.run(ticker.tick())
    assert counts == {"materialised": 0, "reminded": 0, "followed_up": 0,
                      "escalated": 0, "stale_missed": 0}


def test_05_the_daily_report_job_is_guarded_too(monkeypatch):
    monkeypatch.setattr(ticker, "_holds_lock", lambda: False)
    counts = asyncio.run(ticker.course_end_reports())
    assert counts == {"courses": 0, "reports": 0, "messaged": 0}


# ==========================================================================
# what /api/health says about it
# ==========================================================================


def test_06_health_reports_a_lost_lock_rather_than_just_running(monkeypatch):
    """"scheduler: running" on its own was the misleading part."""
    monkeypatch.setattr(ticker, "_scheduler", object())
    monkeypatch.setattr(ticker, "_lock_conn", DeadConn())
    assert ticker.lock_state().startswith("lost")

    monkeypatch.setattr(ticker, "_lock_conn", LiveConn())
    assert ticker.lock_state() == "held"


def test_07_asking_about_the_lock_never_takes_it(monkeypatch):
    """/api/health must not be able to change what it is reporting on."""
    monkeypatch.setattr(ticker, "_scheduler", object())
    monkeypatch.setattr(ticker, "_lock_conn", DeadConn())
    monkeypatch.setattr(ticker, "_acquire_lock",
                        lambda: pytest.fail("health must never take the lock"))
    ticker.lock_state()


# ==========================================================================
# starting up when somebody else still holds the lock
# ==========================================================================


def test_08_the_scheduler_starts_even_without_the_lock(monkeypatch):
    """Refusing to start left no way back, and that killed the product.

    The retry lives in `tick`, which never runs if the scheduler never
    started. So a restart where the lock was held for a few seconds - the
    previous process still closing its connection through the pooler, which
    is *every* restart - left the backend permanently reminder-less. Seen on
    2026-08-31: fifteen minutes up, zero ticks, health cheerfully reporting
    "scheduler: stopped" and nothing recovering it.
    """
    started = {}

    class FakeScheduler:
        def __init__(self, **_k): started["made"] = True
        def add_job(self, *a, **k): started.setdefault("jobs", []).append(k.get("id"))
        def start(self): started["started"] = True
        def shutdown(self, **_k): pass

    # settings is a pydantic model whose computed fields are read-only, so it
    # is replaced wholesale rather than patched attribute by attribute.
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(ticker, "_scheduler", None)
    monkeypatch.setattr(ticker, "AsyncIOScheduler", FakeScheduler)
    monkeypatch.setattr(ticker, "_acquire_lock", lambda: False)
    monkeypatch.setattr(ticker, "settings", SimpleNamespace(
        database_configured=True, tz=ZoneInfo("Asia/Karachi"),
        followup_minutes=15, escalate_minutes=30, timezone="Asia/Karachi"))

    try:
        assert ticker.start_scheduler() is True, \
            "a process without the lock must still start, on standby"
        assert started.get("started")
        assert "dose_tick" in started.get("jobs", [])
    finally:
        monkeypatch.setattr(ticker, "_scheduler", None)


def test_09_a_standby_process_sends_nothing(monkeypatch):
    """Standby has to mean standby - the tick guard is what enforces it."""
    monkeypatch.setattr(ticker, "_lock_conn", None)
    monkeypatch.setattr(ticker, "_acquire_lock", lambda: False)
    assert ticker._holds_lock() is False


def test_10_standby_takes_over_when_the_holder_lets_go(monkeypatch):
    """The failover the old behaviour needed a human for."""
    monkeypatch.setattr(ticker, "_lock_conn", None)
    monkeypatch.setattr(ticker, "_said_standing_down", True)
    monkeypatch.setattr(ticker, "_acquire_lock", lambda: True)
    assert ticker._holds_lock() is True


def test_11_standing_down_is_logged_once_not_every_minute(monkeypatch, caplog):
    """A minute-by-minute ERROR buries the log it is meant to stand out in."""
    import logging

    monkeypatch.setattr(ticker, "_lock_conn", None)
    monkeypatch.setattr(ticker, "_acquire_lock", lambda: False)
    monkeypatch.setattr(ticker, "_said_standing_down", False)

    with caplog.at_level(logging.ERROR, logger="app.scheduler.ticker"):
        for _ in range(5):
            ticker._holds_lock()

    shouts = [r for r in caplog.records if "STANDING DOWN" in r.getMessage()]
    assert len(shouts) == 1, f"said it {len(shouts)} times"
