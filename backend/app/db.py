"""Database engine and session handling for Supabase Postgres.

No Alembic (AGENTS.md section 6): tables come from `SQLModel.metadata.create_all`
at startup. `create_all` only ever CREATEs missing tables - it never alters an
existing one - so a column change during the build means dropping the table by
hand. models.py is frozen at the end of Phase 0 for exactly this reason.

The engine is built lazily. The app must still boot with an empty
DATABASE_URL so `make dev` and `GET /api/health` work before Supabase exists.
"""

from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  - import registers every table on the metadata
from app.config import settings

log = logging.getLogger(__name__)

_engine: Engine | None = None


def get_engine() -> Engine:
    """Return the process-wide engine, creating it on first use.

    Raises RuntimeError if DATABASE_URL is not configured - callers that can
    survive without a database should check `settings.database_configured`
    first rather than catching this.
    """
    global _engine
    if _engine is not None:
        return _engine

    if not settings.database_configured:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and fill in the "
            "Supabase connection string."
        )

    _engine = create_engine(
        settings.sqlalchemy_url,
        echo=False,
        # Supabase free-tier projects pause after inactivity and the pooler
        # drops idle connections; without this the first request after a quiet
        # spell fails on a dead socket.
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
        # Supabase's transaction-mode pooler (port 6543) cannot handle
        # server-side prepared statements. Disabling them costs nothing at our
        # query volume and works on the direct connection too.
        connect_args={"prepare_threshold": None},
    )
    return _engine


def init_db() -> None:
    """Create any missing tables. Safe to call on every startup."""
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    log.info("database ready: %d tables checked", len(SQLModel.metadata.tables))


def check_connection() -> bool:
    """True if the database answers a trivial query right now."""
    if not settings.database_configured:
        return False
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - health check reports, never raises
        log.warning("database check failed: %s", exc)
        return False


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a transactional session."""
    with Session(get_engine()) as session:
        yield session


def session_scope() -> Session:
    """A session for code outside a request (scheduler jobs, scripts, tasks).

    Use as a context manager: `with session_scope() as s: ...`
    """
    return Session(get_engine())
