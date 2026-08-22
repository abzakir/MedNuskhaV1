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

    # --- WhatsApp (Meta Cloud API) ---
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_waba_id: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_api_version: str = "v23.0"

    # --- Alibaba Cloud Model Studio (DashScope) ---
    dashscope_api_key: str = ""

    # --- Voice ---
    google_application_credentials: str = ""
    whisper_model: str = "base"

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
        return bool(self.whatsapp_token and self.whatsapp_phone_number_id)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_configured(self) -> bool:
        return bool(self.sqlalchemy_url)

    def missing_required(self) -> list[str]:
        """Env vars that are empty and will block a real (non-health) request."""
        required = {
            "DATABASE_URL": self.database_url,
            "WHATSAPP_TOKEN": self.whatsapp_token,
            "WHATSAPP_PHONE_NUMBER_ID": self.whatsapp_phone_number_id,
            "WHATSAPP_VERIFY_TOKEN": self.whatsapp_verify_token,
            "DASHSCOPE_API_KEY": self.dashscope_api_key,
        }
        return [name for name, value in required.items() if not value]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
