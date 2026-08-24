"""Where pre-generated voice notes live.

Local disk is the primary store, Supabase Storage the durable copy. That order
is deliberate and is the opposite of how the reports work:

- A report is fetched once, by a person, over a link. Rebuilding it from the
  database costs nothing noticeable.
- A voice note is fetched by the ticker at the exact moment a dose is due, and
  the one thing section 3.4 forbids is synthesising in the reminder path. A
  local file is the only source fast enough to be certain about, and it keeps
  working when `SUPABASE_SERVICE_KEY` is unset - which it currently is.

Keys are content-addressed: the hash of the voice plus the exact sentence. So
"one file per unique dose text" is literally true rather than something the
caller has to remember, two patients on the same medicine at the same hour
share a file, and changing the copy can never serve the old audio.
"""

from __future__ import annotations

import logging
from hashlib import sha256
from pathlib import Path

from app import storage
from app.config import settings

log = logging.getLogger(__name__)

CONTENT_TYPE = "audio/ogg"
#: 16 hex characters is 64 bits - far more than enough to keep a few thousand
#: sentences apart, and short enough to read in a log line.
KEY_CHARS = 16


def cache_dir() -> Path:
    path = Path(settings.voice_cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def key_for(text: str, voice: str | None = None) -> str:
    """The storage key for one spoken sentence.

    Content-addressed, so the same sentence in the same voice is the same file
    no matter which patient, medicine or dose asked for it.
    """
    voice = voice or settings.tts_voice
    digest = sha256(f"{voice}\n{' '.join(text.split())}".encode()).hexdigest()
    return f"{digest[:KEY_CHARS]}.ogg"


def _local(key: str) -> Path:
    return cache_dir() / key


def has_local(key: str) -> bool:
    path = _local(key)
    return path.exists() and path.stat().st_size > 0


def get(key: str) -> bytes | None:
    """The audio for a key: local first, then the archive. None if neither."""
    path = _local(key)
    if has_local(key):
        return path.read_bytes()

    blob = storage.download(settings.supabase_storage_bucket, key)
    if blob:
        # Pull it back into the local cache so the next dose is a disk read.
        try:
            path.write_bytes(blob)
        except OSError as exc:  # noqa: BLE001 - the bytes are still usable
            log.warning("could not cache %s locally: %s", key, exc)
        return blob
    return None


def put(key: str, blob: bytes) -> None:
    """Save audio locally, and archive it if the secret key is configured."""
    try:
        _local(key).write_bytes(blob)
    except OSError as exc:  # noqa: BLE001
        log.error("could not write %s to the local cache: %s", key, exc)

    storage.try_upload(settings.supabase_storage_bucket, key, blob, CONTENT_TYPE)


def stats() -> dict:
    """What is cached, for /api/health and the verification scripts."""
    files = list(cache_dir().glob("*.ogg"))
    return {
        "files": len(files),
        "bytes": sum(f.stat().st_size for f in files),
        "archived": storage.is_configured(),
        "dir": str(cache_dir()),
    }
