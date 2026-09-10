"""Cache-aside helpers for the read-heavy series endpoints.

Keys embed the resolved ``index_run_id`` a response was computed against, so a new
index run naturally invalidates every key built from the old one — nothing here ever
deletes a key. Entries simply age out via TTL (``APIX_API_CACHE_TTL_S``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import orjson

if TYPE_CHECKING:
    from redis.asyncio import Redis


def build_key(namespace: str, /, **parts: object) -> str:
    """``apix:cache:{namespace}:{k=v,...}``, deterministic regardless of kwarg order."""
    rendered = ",".join(f"{k}={v}" for k, v in sorted(parts.items()))
    return f"apix:cache:{namespace}:{rendered}"


async def cache_get_json(redis: Redis, key: str) -> object | None:
    raw = await redis.get(key)
    if raw is None:
        return None
    return cast("object", orjson.loads(raw))


async def cache_set_json(redis: Redis, key: str, value: object, *, ttl_s: int) -> None:
    if ttl_s <= 0:
        return
    await redis.set(key, orjson.dumps(value), ex=ttl_s)


__all__ = ["build_key", "cache_get_json", "cache_set_json"]
