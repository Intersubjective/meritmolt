"""Application configuration from environment."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CrawlerSettings(BaseSettings):
    """TextLake crawler configuration loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Moltbook API (crawler uses dedicated key, Bearer auth)
    mb_crawler_api_key: str
    mb_api_base: str = "https://www.moltbook.com/api/v1"
    mb_rate_limit_rpm: int = 100
    mb_concurrency: int = 10
    mb_http_timeout: float = 15.0
    mb_http_semaphore: int = 10
    mb_http_retry_max_attempts: int = 3

    # Postgres (same instance as MeritMolt, separate database)
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = ""
    postgres_db: str = "textlake"

    @field_validator("postgres_db")
    @classmethod
    def _no_quotes_in_db_name(cls, v: str) -> str:
        if '"' in v:
            raise ValueError("postgres_db must not contain double-quote characters")
        return v

    @property
    def database_url(self) -> str:
        """Async Postgres URL for SQLAlchemy (asyncpg driver)."""
        from urllib.parse import quote_plus

        pw = quote_plus(self.postgres_password)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{pw}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> CrawlerSettings:
    """Return cached settings instance."""
    return CrawlerSettings()  # type: ignore[call-arg]
