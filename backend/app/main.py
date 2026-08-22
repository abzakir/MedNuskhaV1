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

    # The APScheduler ticker is started in Phase 2, guarded against uvicorn
    # --reload spawning it twice (AGENTS.md section 17).

    yield

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
        "missing_env": settings.missing_required(),
    }
