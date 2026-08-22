"""FastAPI application entrypoint - app creation and router mounting.

Run with:  uvicorn app.main:app --app-dir backend --reload
or via:    make dev   /   .\\dev.ps1
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.config import settings
from app.db import check_connection, init_db
from app.scheduler.ticker import is_running, start_scheduler, stop_scheduler
from app.whatsapp.client import close_client
from app.whatsapp.webhook import router as webhook_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mednuskha")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown.

    Startup never hard-fails on a missing database: the health endpoint has to
    answer so `make dev` can be verified before Supabase exists. Anything
    genuinely missing is logged loudly instead.
    """
    missing = settings.missing_required()
    if missing:
        log.warning("env vars not set: %s - see .env.example", ", ".join(missing))

    if settings.database_configured:
        try:
            init_db()
        except Exception as exc:  # noqa: BLE001 - keep the app up, log the cause
            log.error("database init failed: %s", exc)
    else:
        log.warning("DATABASE_URL not set - running without a database")

    # Guarded twice: a module flag for this process, and a Postgres advisory
    # lock so a second worker - or a teammate's dev server pointed at the same
    # Supabase project - cannot fire every reminder again (section 17).
    start_scheduler()

    yield

    stop_scheduler()
    await close_client()
    log.info("shutting down")


app = FastAPI(
    title="MedNuskha",
    description="WhatsApp medication adherence agent for elderly patients.",
    version="0.1.0",
    lifespan=lifespan,
)

# The dashboard is served from a different origin (localhost:3000 in dev,
# Vercel in production), so it needs CORS. The WhatsApp webhook is called
# server-to-server by Meta and is unaffected.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(webhook_router)


def _llm_health() -> dict:
    """Key-pool health. Never contains key material - see llm.KeyRing.status."""
    if not settings.llm_configured:
        return {"status": "no keys", "keys": []}
    from app.agent.llm import ring

    keys = ring().status()
    ready = sum(1 for k in keys if k["state"] == "ready")
    return {
        "status": "ok" if ready else "all keys cooling or dead",
        "ready": ready,
        "total": len(keys),
        "keys": keys,
    }


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    """Liveness and configuration check. Always 200 while the process is up."""
    return {
        "status": "ok",
        "service": "mednuskha",
        "version": app.version,
        "timezone": settings.timezone,
        "database": "connected" if check_connection() else "not connected",
        "whatsapp": "configured" if settings.whatsapp_configured else "not configured",
        "scheduler": "running" if is_running() else "stopped",
        "llm": _llm_health(),
        "missing_env": settings.missing_required(),
    }
