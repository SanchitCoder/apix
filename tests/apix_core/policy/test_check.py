"""check(): gate order, decisions, and the audit trail."""

from __future__ import annotations

from apix_core.models.enums import PolicyDecisionOutcome
from apix_core.provenance.hashing import hash_url
from tests.apix_core.policy._support import (
    DOMAIN,
    build_engine,
    make_config,
    make_source,
)

FARE_URL = f"https://www.{DOMAIN}/fares/DEL-BOM?date=2026-09-10"


def test_allowed_url_passes_every_gate(fake_redis):
    engine, _, _, _ = build_engine(fake_redis)
    decision = engine.check(FARE_URL)
    assert decision.allowed
    assert decision.rule == "allowed"
    assert decision.outcome is PolicyDecisionOutcome.ALLOWED
    assert decision.source_code == "test_source"
    assert decision.url_hash == hash_url(FARE_URL)


def test_every_check_writes_exactly_one_decision(fake_redis):
    engine, _, _, log = build_engine(fake_redis)
    engine.check(FARE_URL)
    engine.check(f"https://{DOMAIN}/booking/x")
    engine.check("https://unrelated.example/fares/")
    assert len(log.decisions) == 3
    assert [d.allowed for d in log.decisions] == [True, False, False]


def test_unknown_host_is_denied(fake_redis):
    engine, _, _, _ = build_engine(fake_redis)
    decision = engine.check("https://not-configured.example/fares/DEL-BOM")
    assert not decision.allowed
    assert decision.rule == "source"
    assert decision.outcome is PolicyDecisionOutcome.DENIED_SOURCE_DISABLED
    assert decision.source_code is None


def test_disabled_source_is_denied(fake_redis):
    config = make_config(make_source(enabled=False))
    engine, _, _, _ = build_engine(fake_redis, config=config)
    decision = engine.check(FARE_URL)
    assert not decision.allowed
    assert decision.rule == "source_enabled"
    assert decision.outcome is PolicyDecisionOutcome.DENIED_SOURCE_DISABLED


def test_source_gate_wins_over_path_gate(fake_redis):
    """The gates run in the documented order: a disabled source is the reason given
    even for a URL that would also fail the path rules."""
    config = make_config(make_source(enabled=False))
    engine, _, _, _ = build_engine(fake_redis, config=config)
    decision = engine.check(f"https://{DOMAIN}/booking/x")
    assert decision.rule == "source_enabled"


def test_robots_disallow_denies_before_path_rules(fake_redis):
    from tests.apix_core.policy._support import RecordingHandler

    handler = RecordingHandler(robots_body="User-agent: *\nDisallow: /fares/private/\n")
    config = make_config(make_source(allowed_paths=["/fares/"]))
    engine, _, _, _ = build_engine(fake_redis, config=config, handler=handler)
    allowed = engine.check(f"https://{DOMAIN}/fares/DEL-BOM")
    denied = engine.check(f"https://{DOMAIN}/fares/private/x")
    assert allowed.allowed
    assert not denied.allowed
    assert denied.rule == "robots"
    assert denied.outcome is PolicyDecisionOutcome.DENIED_ROBOTS


def test_disallowed_path_prefix_is_denied(fake_redis):
    engine, _, _, _ = build_engine(fake_redis)
    decision = engine.check(f"https://{DOMAIN}/booking/manage")
    assert not decision.allowed
    assert decision.rule == "disallowed_paths"
    assert decision.outcome is PolicyDecisionOutcome.DENIED_PATH


def test_path_outside_allow_list_is_denied(fake_redis):
    engine, _, _, _ = build_engine(fake_redis)
    decision = engine.check(f"https://{DOMAIN}/press-releases/2026")
    assert not decision.allowed
    assert decision.rule == "allowed_paths"
    assert decision.outcome is PolicyDecisionOutcome.DENIED_PATH


def test_empty_allow_list_means_any_path_not_disallowed(fake_redis):
    config = make_config(make_source(allowed_paths=[]))
    engine, _, _, _ = build_engine(fake_redis, config=config)
    assert engine.check(f"https://{DOMAIN}/anything/goes").allowed
    assert not engine.check(f"https://{DOMAIN}/booking/x").allowed


def test_rate_limit_denies_with_retry_after(fake_redis):
    config = make_config(make_source(max_requests_per_hour=2))
    engine, _, _, _ = build_engine(fake_redis, config=config)
    assert engine.check(FARE_URL).allowed
    assert engine.check(FARE_URL).allowed
    decision = engine.check(FARE_URL)
    assert not decision.allowed
    assert decision.rule == "rate_limit"
    assert decision.outcome is PolicyDecisionOutcome.DENIED_RATE_LIMIT
    assert decision.retry_after_s is not None and decision.retry_after_s > 0


def test_config_crawl_delay_spaces_out_requests(fake_redis):
    config = make_config(make_source(crawl_delay_s=10.0))
    engine, _, clock, _ = build_engine(fake_redis, config=config)
    assert engine.check(FARE_URL).allowed
    too_soon = engine.check(FARE_URL)
    assert not too_soon.allowed
    assert too_soon.rule == "rate_limit"
    clock.advance(10.0)
    assert engine.check(FARE_URL).allowed


def test_robots_crawl_delay_wins_when_stricter_than_config(fake_redis):
    from tests.apix_core.policy._support import RecordingHandler

    handler = RecordingHandler(robots_body="User-agent: *\nAllow: /\nCrawl-delay: 30\n")
    config = make_config(make_source(crawl_delay_s=1.0))
    engine, _, clock, _ = build_engine(fake_redis, config=config, handler=handler)
    assert engine.check(FARE_URL).allowed
    clock.advance(5.0)  # enough for the config delay, not for the robots delay
    assert not engine.check(FARE_URL).allowed
    clock.advance(30.0)
    assert engine.check(FARE_URL).allowed


def test_tos_staleness_is_rechecked_at_call_time(fake_redis):
    """An engine that stays up for months does not keep collecting on an expired review."""
    engine, _, clock, _ = build_engine(fake_redis)
    assert engine.check(FARE_URL).allowed
    clock.advance(200 * 24 * 3600)
    decision = engine.check(FARE_URL)
    assert not decision.allowed
    assert decision.rule == "tos"
    assert decision.outcome is PolicyDecisionOutcome.DENIED_TOS


def test_subdomain_hosts_match_their_configured_domain(fake_redis):
    engine, _, _, _ = build_engine(fake_redis)
    assert engine.check(f"https://www.{DOMAIN}/fares/x").allowed
    assert engine.check(f"https://booking-api.{DOMAIN}/fares/x").allowed
    # A lookalike suffix is not a subdomain.
    assert not engine.check(f"https://evil-{DOMAIN}/fares/x").allowed
