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

from app import storage
from app.config import settings

log = logging.getLogger(__name__)

CONTENT_TYPE = "application/pdf"
#: Long enough that guessing is hopeless, short enough to sit in a WhatsApp
#: message without wrapping onto three lines.
TOKEN_CHARS = 32


#: Re-exported so callers can keep catching reports.storage.StorageUnavailable.
StorageUnavailable = storage.StorageUnavailable


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


def _bucket() -> str:
    return settings.supabase_reports_bucket


def is_configured() -> bool:
    return storage.is_configured()


def upload(key: str, blob: bytes) -> None:
    """Archive one PDF. Raises StorageUnavailable rather than failing quietly."""
    storage.upload(_bucket(), key, blob, CONTENT_TYPE)


def download(key: str) -> bytes | None:
    """Fetch an archived PDF. None when it is not there, for any reason."""
    return storage.download(_bucket(), key)


def try_upload(key: str, blob: bytes) -> bool:
    """upload(), but a missing key or a dead bucket only costs a log line.

    The course-end job uses this: failing to archive must never stop the
    caretaker being told their report exists.
    """
    return storage.try_upload(_bucket(), key, blob, CONTENT_TYPE)
