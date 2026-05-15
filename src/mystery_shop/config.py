"""Application configuration loaded from environment variables."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RunMode(StrEnum):
    """How voice and LLM calls are dispatched. Matches the `RUN_MODE` env var."""

    LIVE = "live"
    REPLAY = "replay"
    MOCK = "mock"


class Settings(BaseSettings):
    """Validated runtime configuration. Access via `get_settings()`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    run_mode: RunMode = RunMode.MOCK

    database_url: str = Field(
        ...,
        description="SQLAlchemy DSN, e.g. postgresql+psycopg://localhost:5432/mysteryshop",
    )

    anthropic_api_key: SecretStr = Field(..., description="Anthropic API key")

    vapi_api_key: SecretStr | None = None
    vapi_phone_number_id: str | None = None
    vapi_assistant_id: str | None = None
    vapi_webhook_secret: SecretStr | None = None

    ngrok_domain: str | None = None

    log_level: str = "INFO"

    @model_validator(mode="after")
    def _vapi_required_in_live_mode(self) -> Settings:
        if self.run_mode is not RunMode.LIVE:
            return self
        missing = [
            name
            for name, value in (
                ("VAPI_API_KEY", self.vapi_api_key),
                ("VAPI_PHONE_NUMBER_ID", self.vapi_phone_number_id),
                ("VAPI_ASSISTANT_ID", self.vapi_assistant_id),
                ("VAPI_WEBHOOK_SECRET", self.vapi_webhook_secret),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"RUN_MODE=live requires: {', '.join(missing)}")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()  # type: ignore[call-arg]
