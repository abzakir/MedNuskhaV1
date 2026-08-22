"""Environment configuration — one Settings object for the whole backend.

Every env var in AGENTS.md §13 is represented here exactly once. Nothing else
in the codebase reads os.environ directly; import `settings` from here instead.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# repo root: backend/app/config.py -> backend/app -> backend -> <root>
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """All runtime configuration, loaded from the repo-root .env file."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- WhatsApp delivery (GREEN-API) ---
    #: Green API replaced the Meta Cloud API on 2026-08-22 after the team could
    #: not get a Meta Business account. The Meta client is preserved in git
    #: history (commit 70263f4) if we ever go back. See PROJECT_LOG.md.
    green_api_id_instance: str = ""
    green_api_token_instance: str = ""
    green_api_url: str = "https://api.green-api.com"
    #: Green API recommends a separate host for file uploads.
    green_api_media_url: str = "https://media.green-api.com"
    #: Shared secret we append to the webhook path, since Green API has no
    #: equivalent of Meta's hub.verify_token handshake.
    webhook_secret: str = ""

    # --- LLM (Groq now, Alibaba Model Studio when the credits land) ---
    #: Comma-separated POOLS, not single keys. Every free tier has a daily
    #: cap; several keys rotate so one hitting its limit mid-demo does not
    #: stop the system. Singular *_API_KEY is still accepted and merged in.
    groq_api_keys: str = ""
    groq_api_key: str = ""
    dashscope_api_keys: str = ""
    dashscope_api_key: str = ""

    #: Groq hosts Qwen, so the Alibaba/Qwen story survives the swap.
    groq_model: str = "qwen/qwen3.6-27b"
    #: Cloud Whisper - far better on Urdu than the local model, free tier.
    groq_whisper_model: str = "whisper-large-v3"
    dashscope_model: str = "qwen-plus"

    #: qwen3.6-27b is a REASONING model - by default it prefixes every reply
    #: with a <think> block, which corrupts both short patient messages and
    #: JSON parsing. "none" suppresses it. Verified 2026-08-22: with no extra
    #: params the model returned "<think>Here's a thinking process...";
    #: reasoning_format="hidden" returned an EMPTY string; reasoning_effort
    #: "none" returned exactly "ok". Leave blank to disable the parameter.
    groq_reasoning_effort: str = "none"

    #: Seconds a key sits out after a rate-limit response, when the provider
    #: does not send a Retry-After header.
    llm_cooldown_seconds: int = 60

    # --- Voice ---
    #: edge-tts voice id. ur-PK-UzmaNeural (female) or ur-PK-AsadNeural (male).
    tts_voice: str = "ur-PK-UzmaNeural"
    #: Use "small". "base" inverts Urdu negations - "abhi nahi" (not now)
    #: comes back as "ab hi" (right now). Measured, see PROJECT_LOG.md.
    whisper_model: str = "small"

    # --- Data ---
    database_url: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_storage_bucket: str = "voice-notes"

    # --- App ---
    timezone: str = "Asia/Karachi"
    followup_minutes: int = Field(default=15, ge=1)
    escalate_minutes: int = Field(default=30, ge=1)
    next_public_api_base: str = "http://localhost:8000"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_url(self) -> str:
        """DATABASE_URL normalised to the psycopg3 driver SQLModel needs.

        Supabase hands out `postgresql://...` (and older tooling `postgres://`).
        SQLAlchemy would then reach for psycopg2, which we do not install.
        """
        url = self.database_url.strip()
        if not url:
            return ""
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://") :]
        return url

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tz(self) -> ZoneInfo:
        """The single timezone the whole system operates in (§4: Asia/Karachi)."""
        return ZoneInfo(self.timezone)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def whatsapp_configured(self) -> bool:
        return bool(self.green_api_id_instance and self.green_api_token_instance)

    @staticmethod
    def _split(*values: str) -> list[str]:
        """Parse comma/whitespace-separated keys, de-duplicated, order kept."""
        out: list[str] = []
        for value in values:
            for part in (value or "").replace("\n", ",").split(","):
                part = part.strip()
                if part and part not in out:
                    out.append(part)
        return out

    @property
    def groq_keys(self) -> list[str]:
        return self._split(self.groq_api_keys, self.groq_api_key)

    @property
    def dashscope_keys(self) -> list[str]:
        return self._split(self.dashscope_api_keys, self.dashscope_api_key)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def llm_configured(self) -> bool:
        return bool(self.groq_keys or self.dashscope_keys)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def llm_key_count(self) -> int:
        return len(self.groq_keys) + len(self.dashscope_keys)

    @property
    def green_base(self) -> str:
        return f"{self.green_api_url.rstrip('/')}/waInstance{self.green_api_id_instance}"

    @property
    def green_media_base(self) -> str:
        return (f"{self.green_api_media_url.rstrip('/')}"
                f"/waInstance{self.green_api_id_instance}")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_configured(self) -> bool:
        return bool(self.sqlalchemy_url)

    def missing_required(self) -> list[str]:
        """Env vars that are empty and will block a real (non-health) request."""
        required = {
            "DATABASE_URL": self.database_url,
            "GREEN_API_ID_INSTANCE": self.green_api_id_instance,
            "GREEN_API_TOKEN_INSTANCE": self.green_api_token_instance,
            "GROQ_API_KEYS": ",".join(self.groq_keys),
        }
        return [name for name, value in required.items() if not value]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
