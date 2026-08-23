"""Getting a generated report to the person who needs it.

Two separate jobs live here, because they fail independently:

**Archiving** - putting the PDF in Supabase Storage so it survives a redeploy.
This needs `SUPABASE_SERVICE_KEY`. Verified 2026-08-23: the publishable key can
list buckets but every write is refused by row-level security, so without the
secret key this degrades to a warning rather than an exception.

**Sharing** - the link the caretaker taps in WhatsApp. That link cannot carry a
Bearer token, and the `report` table was frozen at the end of Phase 0 with no
column to put a share token in, so the token is derived instead: an HMAC of the
report id under `WEBHOOK_SECRET`. Stateless, unguessable, and no schema change.

The share link points at our own API rather than at a Storage URL on purpose.
Every row in `report` is then openable whether or not the archive upload
happened, and the endpoint can regenerate a missing PDF from the database -
which is the source of truth for every number in it anyway.
"""

from __future__ import annotations

import hmac
import logging
from hashlib import sha256

import httpx

from app.config import settings

log = logging.getLogger(__name__)

CONTENT_TYPE = "application/pdf"
#: Long enough that guessing is hopeless, short enough to sit in a WhatsApp
#: message without wrapping onto three lines.
TOKEN_CHARS = 32


class StorageUnavailable(RuntimeError):
    """Supabase Storage is not configured, or refused the request."""


# --------------------------------------------------------------------------
# share links
# --------------------------------------------------------------------------


def share_token(report_id: str) -> str:
    """An unguessable, stateless token for one report."""
    secret = (settings.webhook_secret or "").encode() or b"mednuskha-dev"
    return hmac.new(secret, report_id.encode(), sha256).hexdigest()[:TOKEN_CHARS]


def token_ok(report_id: str, token: str) -> bool:
    """Constant-time check. A wrong token must not be distinguishable by timing."""
    return hmac.compare_digest(share_token(report_id), (token or "").strip())


def share_url(report_id: str) -> str:
    base = (settings.next_public_api_base or "").rstrip("/")
    return f"{base}/api/reports/{report_id}.pdf?t={share_token(report_id)}"


# --------------------------------------------------------------------------
# the archive
# --------------------------------------------------------------------------


def object_key(patient_id: str, report_id: str) -> str:
    return f"{patient_id}/{report_id}.pdf"


def is_configured() -> bool:
    return bool(settings.supabase_url and settings.supabase_service_key)


def _headers() -> dict[str, str]:
    key = settings.supabase_service_key
    return {"Authorization": f"Bearer {key}", "apikey": key}


def _base() -> str:
    return settings.supabase_url.rstrip("/") + "/storage/v1"


def ensure_bucket() -> None:
    """Create the reports bucket if it is not there. Private, PDFs only."""
    bucket = settings.supabase_reports_bucket
    with httpx.Client(timeout=20) as client:
        existing = client.get(f"{_base()}/bucket/{bucket}", headers=_headers())
        if existing.status_code == 200:
            return
        made = client.post(
            f"{_base()}/bucket", headers=_headers(),
            json={"name": bucket, "id": bucket, "public": False,
                  "allowed_mime_types": [CONTENT_TYPE]},
        )
        if made.status_code >= 300 and "already exists" not in made.text.lower():
            raise StorageUnavailable(
                f"could not create bucket {bucket!r}: "
                f"{made.status_code} {made.text[:200]}")


def upload(key: str, blob: bytes) -> None:
    """Archive one PDF. Raises StorageUnavailable rather than failing quietly."""
    if not is_configured():
        raise StorageUnavailable(
            "SUPABASE_SERVICE_KEY is not set. The publishable key cannot write "
            "to Storage - see .env.example.")

    ensure_bucket()
    bucket = settings.supabase_reports_bucket
    with httpx.Client(timeout=60) as client:
        response = client.post(
            f"{_base()}/object/{bucket}/{key}",
            headers={**_headers(), "Content-Type": CONTENT_TYPE,
                     # Regenerating the same report must overwrite, not 409.
                     "x-upsert": "true"},
            content=blob,
        )
    if response.status_code >= 300:
        raise StorageUnavailable(
            f"upload of {key!r} failed: {response.status_code} "
            f"{response.text[:200]}")
    log.info("archived report %s (%d bytes)", key, len(blob))


def download(key: str) -> bytes | None:
    """Fetch an archived PDF. None when it is not there, for any reason."""
    if not is_configured():
        return None
    bucket = settings.supabase_reports_bucket
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(f"{_base()}/object/{bucket}/{key}",
                                  headers=_headers())
    except httpx.HTTPError as exc:
        log.warning("storage unreachable for %s: %s", key, exc)
        return None
    if response.status_code == 200:
        return response.content
    log.info("no archived copy of %s (%s)", key, response.status_code)
    return None


def try_upload(key: str, blob: bytes) -> bool:
    """upload(), but a missing key or a dead bucket only costs a log line.

    The course-end job uses this: failing to archive must never stop the
    caretaker being told their report exists.
    """
    try:
        upload(key, blob)
        return True
    except StorageUnavailable as exc:
        log.warning("report %s not archived: %s", key, exc)
    except Exception as exc:  # noqa: BLE001 - archiving is never load-bearing
        log.error("report %s not archived: %s", key, exc)
    return False
