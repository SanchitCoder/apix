"""Per-domain rate limiting in Redis.

Three constraints are enforced in one atomic Lua script, so the limiter stays correct
when many collector processes hit the same domain concurrently:

* a **token bucket** smooths bursts (capacity is small; refill rate is the hourly
  allowance spread evenly over the hour);
* a **fixed hourly window counter** is the hard cap: within any one wall-clock hour
  window, grants can never exceed ``max_requests_per_hour``, whatever the bucket says;
* a **minimum interval** between grants honours ``crawl_delay_s``.

Time is passed *into* the script rather than read from Redis, so the limiter is
deterministic under test and every caller in one process shares one clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import time as _wall_clock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    import redis

_MS_PER_HOUR = 3_600_000

# Keys:  KEYS[1] bucket hash, KEYS[2] hourly window counter.
# Args:  now_ms, capacity, refill_per_ms, crawl_delay_ms, hourly_limit,
#        window_end_ms, bucket_ttl_ms, hour_ttl_ms.
# Reply: {granted(0|1), rule, retry_after_ms}.
_TAKE_SCRIPT = """
local bucket = KEYS[1]
local hour = KEYS[2]
local now = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local refill = tonumber(ARGV[3])
local delay = tonumber(ARGV[4])
local limit = tonumber(ARGV[5])
local window_end = tonumber(ARGV[6])
local bucket_ttl = tonumber(ARGV[7])
local hour_ttl = tonumber(ARGV[8])

local state = redis.call('HMGET', bucket, 'tokens', 'updated', 'last_take')
local tokens = tonumber(state[1])
local updated = tonumber(state[2])
local last_take = tonumber(state[3])
if tokens == nil or updated == nil then
  tokens = capacity
  updated = now
end
if now > updated then
  tokens = math.min(capacity, tokens + (now - updated) * refill)
  updated = now
end

local function save()
  redis.call('HSET', bucket, 'tokens', tokens, 'updated', updated)
  if last_take ~= nil then
    redis.call('HSET', bucket, 'last_take', last_take)
  end
  redis.call('PEXPIRE', bucket, bucket_ttl)
end

if last_take ~= nil and delay > 0 and (now - last_take) < delay then
  save()
  return {0, 'crawl_delay', math.ceil(delay - (now - last_take))}
end
if tokens < 1 then
  save()
  return {0, 'bucket', math.ceil((1 - tokens) / refill)}
end
local used = tonumber(redis.call('GET', hour) or '0')
if used >= limit then
  save()
  return {0, 'hourly_cap', math.ceil(window_end - now)}
end
tokens = tokens - 1
last_take = now
save()
redis.call('INCR', hour)
redis.call('PEXPIRE', hour, hour_ttl)
return {1, 'ok', 0}
"""


@dataclass(frozen=True, slots=True)
class RateLimitVerdict:
    """Outcome of one attempted take."""

    granted: bool
    rule: str  # "ok" | "crawl_delay" | "bucket" | "hourly_cap"
    retry_after_s: float


class TokenBucketLimiter:
    """Atomic per-domain rate limiter. Safe under arbitrary concurrency.

    ``clock`` returns epoch seconds; it exists so tests control time. All state lives
    in Redis, namespaced under ``apix:rl:``, and expires on its own when a domain goes
    quiet.
    """

    def __init__(
        self,
        client: redis.Redis,
        *,
        clock: Callable[[], float] = _wall_clock,
        default_burst: int = 5,
    ) -> None:
        if default_burst < 1:
            raise ValueError("default_burst must be >= 1")
        self._clock = clock
        self._default_burst = default_burst
        self._take = client.register_script(_TAKE_SCRIPT)

    def take(
        self,
        domain: str,
        *,
        crawl_delay_s: float,
        max_requests_per_hour: int,
        burst: int | None = None,
        now: float | None = None,
    ) -> RateLimitVerdict:
        """Try to take one request slot for ``domain``.

        Never sleeps and never retries: a refused take reports how long to wait so the
        caller can schedule, which keeps the atomicity boundary inside Redis.
        """
        if max_requests_per_hour < 1:
            raise ValueError("max_requests_per_hour must be >= 1")
        capacity = min(max_requests_per_hour, burst if burst is not None else self._default_burst)
        now_ms = int((now if now is not None else self._clock()) * 1000)
        window = now_ms // _MS_PER_HOUR
        refill_per_ms = max_requests_per_hour / _MS_PER_HOUR
        reply = self._take(
            keys=[f"apix:rl:bucket:{domain}", f"apix:rl:hour:{domain}:{window}"],
            args=[
                str(now_ms),
                str(capacity),
                repr(refill_per_ms),
                str(int(crawl_delay_s * 1000)),
                str(max_requests_per_hour),
                str((window + 1) * _MS_PER_HOUR),
                str(2 * _MS_PER_HOUR),
                str(2 * _MS_PER_HOUR),
            ],
        )
        granted, rule, retry_ms = _parse_reply(reply)
        return RateLimitVerdict(granted=granted, rule=rule, retry_after_s=retry_ms / 1000)


def _parse_reply(reply: object) -> tuple[bool, str, int]:
    if not isinstance(reply, (list, tuple)) or len(reply) != 3:
        raise RuntimeError(f"rate limiter script returned malformed reply: {reply!r}")
    granted_raw, rule_raw, retry_raw = reply
    rule = rule_raw.decode() if isinstance(rule_raw, bytes) else str(rule_raw)
    return bool(int(str(granted_raw))), rule, int(str(retry_raw))


__all__ = ["RateLimitVerdict", "TokenBucketLimiter"]
