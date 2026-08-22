"""REST API for the Next.js dashboard.

Built in Phase 4. Endpoints the dashboard needs:
  GET  /api/families/{id}                    family overview
  GET  /api/patients/{id}                    patient detail
  GET  /api/patients/{id}/today              today's doses (polled every 5s)
  POST /api/patients                         add a patient
  POST /api/medicines/lookup                 knowledge.fetch_draft -> draft
  POST /api/medicines                        save_confirmed + medicine + schedule
  GET  /api/patients/{id}/report.pdf         Phase 6
  POST /api/patients/{id}/prescriptions      Phase 7

GET /api/health lives in main.py.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["dashboard"])
