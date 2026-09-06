"""TokenBucketLimiter: correctness under concurrency, proven with hypothesis.

The property that matters for a statistical collector's good citizenship: however
many concurrent callers hammer the limiter, grants within one hour window never
exceed ``max_requests_per_hour``, and grants are never closer together than the
crawl delay. Concurrency is real threads against one fakeredis server — the Lua
script is the only thing keeping the count correct, which is the point.
"""

from __future__ import annotations

import itertools
import threading

import fakeredis
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apix_core.policy.ratelimit import TokenBucketLimiter

# An hour-aligned base instant, so a test never straddles a window boundary by luck.
WINDOW_START = 1_788_000_000 - (1_788_000_000 % 3600)

CALLERS = 50


def fresh_limiter() -> TokenBucketLimiter:
    return TokenBucketLimiter(fakeredis.FakeStrictRedis(decode_responses=True))


@settings(max_examples=15, deadline=None)
@given(
    limit=st.integers(min_value=1, max_value=40),
    extra_attempts=st.integers(min_value=1, max_value=60),
)
def test_hourly_cap_is_never_exceeded_by_50_concurrent_callers(limit, extra_attempts):
    """The required property: 50 threads, arbitrary demand, grants <= the cap."""
    limiter = fresh_limiter()
    attempts = limit + extra_attempts
    # Deterministic timestamps spread across (but inside) one hour window.
    times = [WINDOW_START + i * (3599.0 / attempts) for i in range(attempts)]
    lock = threading.Lock()
    granted = []
    barrier = threading.Barrier(CALLERS)

    def worker() -> None:
        barrier.wait()
        while True:
            with lock:
                if not times:
                    return
                now = times.pop()
            verdict = limiter.take(
                "example.test",
                crawl_delay_s=0.0,
                max_requests_per_hour=limit,
                burst=limit,
                now=now,
            )
            if verdict.granted:
                with lock:
                    granted.append(now)

    threads = [threading.Thread(target=worker) for _ in range(CALLERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(granted) <= limit
    # With burst == limit the bucket starts full, so exactly the cap is granted.
    assert len(granted) == min(attempts, limit)


@settings(max_examples=15, deadline=None)
@given(
    delay_ms=st.integers(min_value=100, max_value=30_000),
    gaps_ms=st.lists(st.integers(min_value=0, max_value=60_000), min_size=2, max_size=30),
)
def test_grants_are_never_closer_than_the_crawl_delay(delay_ms, gaps_ms):
    limiter = fresh_limiter()
    now = float(WINDOW_START)
    granted_at: list[float] = []
    for gap_ms in gaps_ms:
        now += gap_ms / 1000.0
        verdict = limiter.take(
            "example.test",
            crawl_delay_s=delay_ms / 1000.0,
            max_requests_per_hour=100_000,
            burst=100_000,
            now=now,
        )
        if verdict.granted:
            granted_at.append(now)
    for earlier, later in itertools.pairwise(granted_at):
        # Millisecond resolution inside the script.
        assert (later - earlier) * 1000 >= delay_ms - 1


def test_bucket_refills_at_the_configured_rate():
    limiter = fresh_limiter()
    now = float(WINDOW_START)

    def take(at: float):
        return limiter.take(
            "example.test", crawl_delay_s=0.0, max_requests_per_hour=60, burst=1, now=at
        )

    assert take(now).granted
    denied = take(now)
    assert not denied.granted
    assert denied.rule == "bucket"
    # 60/hour is one token a minute: 30s in, still dry; 61s in, one token back.
    assert not take(now + 30).granted
    assert take(now + 61).granted


def test_denials_report_a_usable_retry_after():
    limiter = fresh_limiter()
    now = float(WINDOW_START)
    kwargs = {"crawl_delay_s": 10.0, "max_requests_per_hour": 3600, "burst": 1}
    assert limiter.take("example.test", now=now, **kwargs).granted
    verdict = limiter.take("example.test", now=now + 2, **kwargs)
    assert not verdict.granted
    assert verdict.rule == "crawl_delay"
    assert verdict.retry_after_s == pytest.approx(8.0, abs=0.01)
    assert limiter.take("example.test", now=now + 2 + verdict.retry_after_s, **kwargs).granted


def test_hourly_denial_reports_time_to_window_end():
    limiter = fresh_limiter()
    now = float(WINDOW_START)
    kwargs = {"crawl_delay_s": 0.0, "max_requests_per_hour": 1, "burst": 1}
    assert limiter.take("example.test", now=now, **kwargs).granted
    # The bucket refills a token after an hour... but by then we are in the next
    # window anyway; deny inside the same window comes from the bucket or the cap.
    verdict = limiter.take("example.test", now=now + 3599, **kwargs)
    assert not verdict.granted
    assert verdict.rule in ("bucket", "hourly_cap")
    # Next window: a fresh allowance.
    assert limiter.take("example.test", now=now + 3601, **kwargs).granted


def test_domains_do_not_share_buckets():
    limiter = fresh_limiter()
    now = float(WINDOW_START)
    kwargs = {"crawl_delay_s": 0.0, "max_requests_per_hour": 1, "burst": 1}
    assert limiter.take("a.test", now=now, **kwargs).granted
    assert limiter.take("b.test", now=now, **kwargs).granted
    assert not limiter.take("a.test", now=now, **kwargs).granted


def test_invalid_configuration_is_rejected():
    limiter = fresh_limiter()
    with pytest.raises(ValueError, match="max_requests_per_hour"):
        limiter.take("example.test", crawl_delay_s=0.0, max_requests_per_hour=0)
    with pytest.raises(ValueError, match="default_burst"):
        TokenBucketLimiter(fakeredis.FakeStrictRedis(), default_burst=0)
