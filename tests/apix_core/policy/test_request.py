"""request(): the single egress point — denial, pushback, and challenge behaviour."""

from __future__ import annotations

import httpx
import pytest
from structlog.testing import capture_logs

from apix_core.models.enums import PolicyDecisionOutcome
from apix_core.policy import CaptchaDetected, PolicyDenied
from tests.apix_core.policy._support import (
    DOMAIN,
    build_engine,
    make_config,
    make_source,
)

FARE_URL = f"https://www.{DOMAIN}/fares/DEL-BOM"
CAPTCHA_BODY = '<html><div class="g-recaptcha" data-sitekey="xyz"></div></html>'


def test_denied_url_raises_without_touching_the_network(fake_redis):
    """The required test: PolicyDenied for a disallowed path, and no request is made."""
    engine, handler, _, log = build_engine(fake_redis)
    with pytest.raises(PolicyDenied) as excinfo:
        engine.request(f"https://www.{DOMAIN}/booking/manage")
    assert excinfo.value.decision.rule == "disallowed_paths"
    assert handler.non_robots_requests == []
    # The denial is on the audit trail even though nothing was fetched.
    assert log.decisions[-1].outcome is PolicyDecisionOutcome.DENIED_PATH


def test_allowed_request_goes_out_with_our_user_agent(fake_redis):
    engine, handler, _, _ = build_engine(fake_redis)
    response = engine.request(FARE_URL)
    assert response.status_code == 200
    (sent,) = handler.non_robots_requests
    assert sent.headers["User-Agent"].startswith("APIx-Test/1.0")


def test_three_consecutive_pushbacks_disable_the_source(fake_redis):
    engine, handler, _, _ = build_engine(fake_redis)
    handler.responses["/fares/DEL-BOM"] = httpx.Response(403, text="forbidden")
    with capture_logs() as logs:
        for _ in range(3):
            assert engine.request(FARE_URL).status_code == 403
    assert any(e["event"] == "policy_source_disabled" for e in logs)

    cooled = engine.check(FARE_URL)
    assert not cooled.allowed
    assert cooled.rule == "cooling_off"
    assert cooled.retry_after_s is not None and cooled.retry_after_s > 0


def test_cooling_off_expires(fake_redis):
    engine, handler, _, _ = build_engine(fake_redis, cooling_off_s=60.0)
    handler.responses["/fares/DEL-BOM"] = httpx.Response(429, text="slow down")
    for _ in range(3):
        engine.request(FARE_URL)
    assert not engine.check(FARE_URL).allowed
    # fakeredis TTLs run on the wall clock, so expire the key the way Redis would.
    fake_redis.delete("apix:policy:cooloff:test_source")
    handler.responses.pop("/fares/DEL-BOM")
    assert engine.request(FARE_URL).status_code == 200


def test_a_success_resets_the_failure_count(fake_redis):
    engine, handler, clock, _ = build_engine(fake_redis)
    handler.responses["/fares/DEL-BOM"] = httpx.Response(403)
    engine.request(FARE_URL)
    clock.advance(60)
    engine.request(FARE_URL)
    clock.advance(60)
    handler.responses.pop("/fares/DEL-BOM")
    engine.request(FARE_URL)  # 200 — the streak is broken
    clock.advance(60)
    handler.responses["/fares/DEL-BOM"] = httpx.Response(403)
    engine.request(FARE_URL)
    clock.advance(60)
    engine.request(FARE_URL)
    clock.advance(60)
    # Only two consecutive failures since the success: still collectable.
    assert engine.check(FARE_URL).allowed


def test_captcha_blocks_the_run_and_disables_the_source(fake_redis):
    blocked_runs: list[tuple[str, str]] = []
    engine, handler, _, log = build_engine(
        fake_redis,
        mark_run_blocked=lambda code, error_class: blocked_runs.append((code, error_class)),
    )
    handler.responses["/fares/DEL-BOM"] = httpx.Response(200, text=CAPTCHA_BODY)

    with capture_logs() as logs, pytest.raises(CaptchaDetected) as excinfo:
        engine.request(FARE_URL)

    assert excinfo.value.signature == "recaptcha"
    assert blocked_runs == [("test_source", "captcha")]
    assert any(e["event"] == "policy_source_blocked_by_challenge" for e in logs)
    assert log.decisions[-1].outcome is PolicyDecisionOutcome.DENIED_CAPTCHA
    # The source is now cooling off: nothing further goes out.
    followup = engine.check(FARE_URL)
    assert not followup.allowed
    assert followup.rule == "cooling_off"


def test_captcha_handling_works_without_a_run_hook(fake_redis):
    engine, handler, _, _ = build_engine(fake_redis)
    handler.responses["/fares/DEL-BOM"] = httpx.Response(200, text=CAPTCHA_BODY)
    with pytest.raises(CaptchaDetected):
        engine.request(FARE_URL)


def test_engine_is_a_context_manager(fake_redis):
    engine, _, _, _ = build_engine(fake_redis)
    with engine as e:
        assert e.check(FARE_URL).allowed


def test_rate_limited_request_raises_policy_denied(fake_redis):
    config = make_config(make_source(max_requests_per_hour=1))
    engine, handler, _, _ = build_engine(fake_redis, config=config)
    engine.request(FARE_URL)
    with pytest.raises(PolicyDenied) as excinfo:
        engine.request(FARE_URL)
    assert excinfo.value.decision.rule == "rate_limit"
    assert len(handler.non_robots_requests) == 1
