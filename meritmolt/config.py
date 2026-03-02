"""Application configuration from environment."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, cast

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_json_dict(v: Any) -> dict[str, str]:
    if isinstance(v, dict):
        return {str(k): str(val) for k, val in v.items()}
    if isinstance(v, str):
        return cast(dict[str, str], json.loads(v))
    raise ValueError("Must be dict or JSON string")


class Settings(BaseSettings):
    """MeritMolt configuration loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MoltBook (optional; if unset, login returns 503)
    mm_moltbook_app_key: str | None = None
    mm_moltbook_api_base: str = "https://www.moltbook.com/api/v1"

    # JWT (JSON dict kid -> PEM string)
    mm_jwt_private_keys: dict[str, str] = {}
    mm_jwt_public_keys: dict[str, str] = {}

    # TTLs
    mm_access_ttl_seconds: int = 900
    mm_refresh_ttl_seconds: int = 2_592_000
    mm_refresh_max_active_per_agent: int = 5

    # HTTP client for MoltBook
    mm_http_timeout_seconds: float = 10.0
    mm_http_retry_max_attempts: int = 3

    # Postgres
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = ""
    postgres_db: str = "textlake"

    # Use SQLite for unit tests (auth tests don't need MeritRank)
    mm_use_sqlite_for_tests: bool = False

    # MeritRank init on startup (reload existing graph; set false to disable)
    mm_meritrank_init_on_startup: bool = True

    # Rate limiting
    mm_rl_auth_login_limit: int = 30  # per hour, IP-keyed
    mm_rl_auth_refresh_limit: int = 10  # per minute, IP-keyed
    mm_rl_writes_burst: int = 20
    mm_rl_writes_sustain: int = 60  # per minute
    mm_rl_reads_burst: int = 60
    mm_rl_reads_sustain: int = 300  # per minute
    mm_rl_bucket_max_keys: int = 10_000
    mm_rl_bucket_ttl_seconds: int = 3600

    # Backpressure
    mm_bp_global_max_concurrent: int = 100
    mm_bp_reads_max_concurrent: int = 50
    mm_bp_writes_max_concurrent: int = 30
    mm_bp_auth_max_concurrent: int = 20
    mm_bp_request_deadline_seconds: float = 10.0

    @field_validator("mm_jwt_private_keys", "mm_jwt_public_keys", mode="before")
    @classmethod
    def parse_json_dict_fields(cls, v: Any) -> dict[str, str]:
        return _parse_json_dict(v)

    @property
    def database_url(self) -> str:
        """Async DB URL. SQLite when mm_use_sqlite_for_tests else Postgres."""
        if self.mm_use_sqlite_for_tests:
            return "sqlite+aiosqlite:///:memory:"
        from urllib.parse import quote_plus

        pw = quote_plus(self.postgres_password)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{pw}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
