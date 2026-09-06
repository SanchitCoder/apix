"""Process configuration, read from the environment and validated on load.

Everything here maps to a variable documented in ``.env.example``. Nothing here holds a
default that would silently work in production — an unset ``APIX_SECRET_KEY`` in a
non-local environment is a startup failure, not a warning.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


class ProxyRotation(StrEnum):
    PER_REQUEST = "per_request"
    PER_SESSION = "per_session"
    STICKY = "sticky"


class Settings(BaseSettings):
    """Validated APIx settings. Instantiate via :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_prefix="APIX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    env: Environment = Environment.LOCAL
    log_level: str = "INFO"
    log_format: str = "json"

    database_url: str = "postgresql+asyncpg://apix:apix@localhost:5432/apix"
    database_sync_url: str = "postgresql+psycopg2://apix:apix@localhost:5432/apix"
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_pool_max_overflow: int = Field(default=5, ge=0, le=100)
    db_echo: bool = False

    redis_url: str = "redis://localhost:6379/0"
    redis_rate_limit_db: int = Field(default=1, ge=0, le=15)

    proxy_enabled: bool = False
    proxy_pool_url: str | None = None
    proxy_username: str | None = None
    proxy_password: SecretStr | None = None
    proxy_rotation: ProxyRotation = ProxyRotation.PER_REQUEST
    proxy_max_concurrency: int = Field(default=4, ge=1, le=64)
    proxy_country: str = "IN"

    prefect_api_url: str = "http://localhost:4200/api"
    prefect_work_pool: str = "apix-default"

    secret_key: SecretStr = SecretStr("dev-only-not-a-secret")
    api_host: str = "0.0.0.0"  # noqa: S104 — containerised service, bound by compose
    api_port: int = Field(default=8000, ge=1, le=65535)
    api_cors_origins: str = "http://localhost:5173"
    api_page_size_default: int = Field(default=100, ge=1, le=1000)
    api_page_size_max: int = Field(default=1000, ge=1, le=10000)

    user_agent: str = "APIx-StatisticalCollector/0.1 (+contact unset)"
    respect_robots: bool = True
    default_crawl_delay_s: float = Field(default=2.0, ge=0.0)

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list. Empty string means "no cross-origin access"."""
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @field_validator("respect_robots")
    @classmethod
    def _robots_is_not_optional(cls, value: bool) -> bool:
        # CLAUDE.md guardrail: there is no configuration in which we ignore robots.txt.
        if not value:
            raise ValueError(
                "APIX_RESPECT_ROBOTS cannot be false. Robots compliance is enforced in "
                "code, not configured away."
            )
        return value

    @model_validator(mode="after")
    def _deployed_environments_need_real_secrets(self) -> Settings:
        if self.env in (Environment.STAGING, Environment.PRODUCTION):
            if self.secret_key.get_secret_value() == "dev-only-not-a-secret":
                raise ValueError(f"APIX_SECRET_KEY must be set in env={self.env}")
            if self.api_page_size_max < self.api_page_size_default:
                raise ValueError("APIX_API_PAGE_SIZE_MAX must be >= APIX_API_PAGE_SIZE_DEFAULT")
        return self

    @model_validator(mode="after")
    def _proxy_config_is_coherent(self) -> Settings:
        if self.proxy_enabled and not self.proxy_pool_url:
            raise ValueError("APIX_PROXY_POOL_URL is required when APIX_PROXY_ENABLED is true")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
