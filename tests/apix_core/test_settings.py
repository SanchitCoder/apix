"""Settings validation. The guardrails in CLAUDE.md are enforced here, not documented."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apix_core.settings import Environment, Settings, get_settings


def _settings(**overrides: object) -> Settings:
    # _env_file=None so a developer's local .env cannot change the result of a test.
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_defaults_are_local_and_safe() -> None:
    settings = _settings()
    assert settings.env is Environment.LOCAL
    assert settings.respect_robots is True


def test_robots_compliance_cannot_be_configured_away() -> None:
    """CLAUDE.md guardrail: there is no environment in which robots.txt is ignored."""
    with pytest.raises(ValidationError, match="cannot be false"):
        _settings(respect_robots=False)


def test_production_requires_a_real_secret_key() -> None:
    with pytest.raises(ValidationError, match="APIX_SECRET_KEY must be set"):
        _settings(env="production")


def test_production_accepts_a_supplied_secret_key() -> None:
    settings = _settings(env="production", secret_key="a-real-secret")
    assert settings.env is Environment.PRODUCTION


def test_proxy_must_have_a_pool_url_when_enabled() -> None:
    with pytest.raises(ValidationError, match="APIX_PROXY_POOL_URL is required"):
        _settings(proxy_enabled=True)


def test_secrets_are_not_printed_in_a_repr() -> None:
    """A settings object ends up in logs and tracebacks; the key must not travel with it."""
    assert "a-real-secret" not in repr(_settings(secret_key="a-real-secret"))


def test_cors_origins_parse_into_a_list() -> None:
    settings = _settings(api_cors_origins="http://a.test, http://b.test ,")
    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()


def test_production_rejects_an_incoherent_page_size_ceiling() -> None:
    """A max below the default would silently hand every client a truncated page."""
    with pytest.raises(ValidationError, match="PAGE_SIZE_MAX must be >="):
        _settings(
            env="production",
            secret_key="a-real-secret",
            api_page_size_default=500,
            api_page_size_max=100,
        )
