"""Supabase Storage, for whatever needs a bucket.

Two callers: `reports/storage.py` archives PDFs, `voice/store.py` archives
pre-generated voice notes. They keep their own key schemes and their own
fallbacks; what lives here is the part that is identical for both and would
otherwise rot in one copy while being fixed in the other.

**Writing needs the SECRET key, not the publishable one.** Verified
2026-08-23: the publishable key lists buckets happily, but both bucket
creation and object upload come back `new row violates row-level security
policy`. Every write path here therefore degrades to a warning rather than an
exception, and both callers keep a way to work without it.

Not in the AGENTS.md section 7 layout - added 2026-08-23 when voice notes
became the second thing needing a bucket. Logged in PROJECT_LOG.md.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)


class StorageUnavailable(RuntimeError):
    """Supabase Storage is not configured, or refused the request."""


def is_configured() -> bool:
    return bool(settings.supabase_url and settings.supabase_service_key)


def _headers() -> dict[str, str]:
    key = settings.supabase_service_key
    return {"Authorization": f"Bearer {key}", "apikey": key}


def _base() -> str:
    return settings.supabase_url.rstrip("/") + "/storage/v1"


def ensure_bucket(bucket: str, *, mime_types: list[str] | None = None) -> None:
    """Create a private bucket if it is not already there."""
    with httpx.Client(timeout=20) as client:
        existing = client.get(f"{_base()}/bucket/{bucket}", headers=_headers())
        if existing.status_code == 200:
            return
        body: dict = {"name": bucket, "id": bucket, "public": False}
        if mime_types:
            body["allowed_mime_types"] = mime_types
        made = client.post(f"{_base()}/bucket", headers=_headers(), json=body)
        if made.status_code >= 300 and "already exists" not in made.text.lower():
            raise StorageUnavailable(
                f"could not create bucket {bucket!r}: "
                f"{made.status_code} {made.text[:200]}")


def upload(bucket: str, key: str, blob: bytes, content_type: str) -> None:
    """Put one object. Raises StorageUnavailable rather than failing quietly."""
    if not is_configured():
        raise StorageUnavailable(
            "SUPABASE_SERVICE_KEY is not set. The publishable key cannot write "
            "to Storage - see .env.example.")

    ensure_bucket(bucket, mime_types=[content_type])
    with httpx.Client(timeout=60) as client:
        response = client.post(
            f"{_base()}/object/{bucket}/{key}",
            headers={**_headers(), "Content-Type": content_type,
                     # Regenerating the same object must overwrite, not 409.
                     "x-upsert": "true"},
            content=blob,
        )
    if response.status_code >= 300:
        raise StorageUnavailable(
            f"upload of {key!r} failed: {response.status_code} "
            f"{response.text[:200]}")
    log.info("stored %s/%s (%d bytes)", bucket, key, len(blob))


def download(bucket: str, key: str) -> bytes | None:
    """Fetch one object. None when it is not there, for any reason."""
    if not is_configured():
        return None
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(f"{_base()}/object/{bucket}/{key}",
                                  headers=_headers())
    except httpx.HTTPError as exc:
        log.warning("storage unreachable for %s/%s: %s", bucket, key, exc)
        return None
    if response.status_code == 200:
        return response.content
    log.info("no stored copy of %s/%s (%s)", bucket, key, response.status_code)
    return None


def try_upload(bucket: str, key: str, blob: bytes, content_type: str) -> bool:
    """upload(), but a missing key or a dead bucket only costs a log line.

    Both callers use this: archiving is never allowed to be the reason a
    patient misses a reminder or a caretaker misses a report.
    """
    try:
        upload(bucket, key, blob, content_type)
        return True
    except StorageUnavailable as exc:
        log.warning("%s/%s not archived: %s", bucket, key, exc)
    except Exception as exc:  # noqa: BLE001 - archiving is never load-bearing
        log.error("%s/%s not archived: %s", bucket, key, exc)
    return False
