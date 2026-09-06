"""Startup validation: an engine cannot exist around a non-collectable config."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from apix_core.config.loader import ConfigError
from apix_core.config.sources import SourceEntry, SourcesConfig
from apix_core.models.enums import TosVerdict
from apix_core.policy import InMemoryDecisionLog, PolicyStartupError, load_policy_engine
from tests.apix_core.policy._support import (
    USER_AGENT,
    FakeClock,
    build_engine,
    make_config,
    make_source,
)

STALE_REVIEW = datetime(2026, 1, 5, tzinfo=UTC)  # 242 days before BASE_TIME


def test_stale_tos_review_fails_startup(fake_redis):
    """The required test: a review older than 180 days refuses to start."""
    config = make_config(make_source(tos_reviewed_at=STALE_REVIEW))
    with pytest.raises(PolicyStartupError, match="days old"):
        build_engine(fake_redis, config=config)


def test_review_at_exactly_180_days_still_starts(fake_redis):
    config = make_config(make_source(tos_reviewed_at=datetime(2026, 3, 8, 12, 0, tzinfo=UTC)))
    engine, *_ = build_engine(fake_redis, config=config)
    assert engine is not None


def test_naive_review_timestamp_is_treated_as_utc(fake_redis):
    config = make_config(make_source(tos_reviewed_at=datetime(2026, 1, 5, 0, 0)))  # naive, stale
    with pytest.raises(PolicyStartupError):
        build_engine(fake_redis, config=config)


def test_disabled_sources_are_not_startup_blockers(fake_redis):
    """A stale review on a disabled source is fine — nothing will be collected."""
    config = make_config(
        make_source("live_ok"),
        make_source("stale_but_off", enabled=False, tos_reviewed_at=STALE_REVIEW),
    )
    engine, *_ = build_engine(fake_redis, config=config)
    assert engine is not None


def test_schema_already_refuses_enabled_unreviewed_source():
    """First line of defence: the Pydantic schema will not even validate it."""
    with pytest.raises(ValueError, match="Only PERMITTED sources may be enabled"):
        make_source(tos_verdict=TosVerdict.NOT_REVIEWED, tos_reviewed_at=None, tos_url=None)


def test_engine_refuses_a_config_that_dodged_schema_validation(fake_redis):
    """Second line of defence: model_construct bypasses validators; the engine does not care."""
    good = make_source()
    smuggled = SourceEntry.model_construct(
        code="smuggled",
        display_name="Smuggled",
        domain="smuggled.test",
        source_type=good.source_type,
        enabled=True,
        policy=good.policy.model_construct(
            **{**dict(good.policy), "tos_verdict": TosVerdict.AMBIGUOUS}
        ),
    )
    config = SourcesConfig.model_construct(version="test", sources=[good, smuggled])
    with pytest.raises(PolicyStartupError, match="AMBIGUOUS"):
        build_engine(fake_redis, config=config)


def test_missing_review_date_fails_startup(fake_redis):
    good = make_source()
    no_date = SourceEntry.model_construct(
        code="nodate",
        display_name="No date",
        domain="nodate.test",
        source_type=good.source_type,
        enabled=True,
        policy=good.policy.model_construct(**{**dict(good.policy), "tos_reviewed_at": None}),
    )
    config = SourcesConfig.model_construct(version="t", sources=[no_date])
    with pytest.raises(PolicyStartupError, match="tos_reviewed_at is unset"):
        build_engine(fake_redis, config=config)


SOURCES_YAML = """\
version: "test"
sources:
  - code: yaml_source
    display_name: "From YAML"
    domain: example.test
    source_type: OTA
    enabled: true
    policy:
      robots_url: "https://example.test/robots.txt"
      allowed_paths: ["/fares/"]
      disallowed_paths: []
      crawl_delay_s: 0.0
      max_requests_per_hour: 100
      tos_url: "https://example.test/tos"
      tos_reviewed_at: {reviewed_at}
      tos_verdict: PERMITTED
      legal_basis: TOS_PERMITTED
"""


def _write_sources(tmp_config_dir, reviewed_at: str) -> None:
    (tmp_config_dir / "sources.yaml").write_text(SOURCES_YAML.format(reviewed_at=reviewed_at))


def test_load_policy_engine_reads_and_validates_the_file(fake_redis, tmp_config_dir):
    _write_sources(tmp_config_dir, "2026-08-15T00:00:00Z")
    engine = load_policy_engine(
        redis_client=fake_redis,
        decision_log=InMemoryDecisionLog(),
        user_agent=USER_AGENT,
        config_dir=tmp_config_dir,
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        clock=FakeClock(),
    )
    assert engine is not None


def test_load_policy_engine_refuses_stale_yaml(fake_redis, tmp_config_dir):
    _write_sources(tmp_config_dir, "2026-01-05T00:00:00Z")
    with pytest.raises(PolicyStartupError):
        load_policy_engine(
            redis_client=fake_redis,
            decision_log=InMemoryDecisionLog(),
            user_agent=USER_AGENT,
            config_dir=tmp_config_dir,
            clock=FakeClock(),
        )


def test_load_policy_engine_refuses_a_missing_file(fake_redis, tmp_config_dir):
    with pytest.raises(ConfigError, match="not found"):
        load_policy_engine(
            redis_client=fake_redis,
            decision_log=InMemoryDecisionLog(),
            user_agent=USER_AGENT,
            config_dir=tmp_config_dir,
        )
