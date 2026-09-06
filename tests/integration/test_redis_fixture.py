"""The fake Redis fixture works and never opens a socket."""

from __future__ import annotations


def test_fake_redis_round_trips(fake_redis) -> None:
    fake_redis.set("apix:ratelimit:example_src", "10")
    assert fake_redis.get("apix:ratelimit:example_src") == "10"


def test_fake_redis_supports_the_token_bucket_primitives(fake_redis) -> None:
    """Phase 2's rate limiter needs atomic decrement and TTL; prove they are available."""
    key = "apix:bucket:example_src"
    fake_redis.set(key, 5, ex=3600)
    assert fake_redis.decr(key) == 4
    assert 0 < fake_redis.ttl(key) <= 3600
