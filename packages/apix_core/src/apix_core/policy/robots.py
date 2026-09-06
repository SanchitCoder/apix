"""robots.txt fetching, caching and interpretation.

The engine consults robots.txt before every request. Fetching it on every check would
itself be impolite, so the file is cached in Redis per domain: fresh for 24 hours,
then revalidated with ``If-None-Match`` so an unchanged file costs a 304, not a body.

Convention for missing/broken files follows :mod:`urllib.robotparser`:

* 4xx (no robots.txt published) — everything is allowed by robots;
* 5xx or a transport failure with no usable cache — everything is disallowed, because
  "we could not read the rules" must never degrade into "there are no rules".
"""

from __future__ import annotations

from dataclasses import dataclass
from time import time as _wall_clock
from typing import TYPE_CHECKING
from urllib.robotparser import RobotFileParser

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable

    import redis

_KEY_PREFIX = "apix:policy:robots:"


@dataclass(frozen=True, slots=True)
class RobotsInfo:
    """A parsed robots.txt plus the crawl delay it declares for our user agent."""

    parser: RobotFileParser
    crawl_delay_s: float | None
    from_cache: bool

    def allows(self, user_agent: str, url: str) -> bool:
        return self.parser.can_fetch(user_agent, url)


class RobotsCache:
    """Per-domain robots.txt, cached in Redis, revalidated by ETag."""

    def __init__(
        self,
        client: redis.Redis,
        http: httpx.Client,
        *,
        user_agent: str,
        fresh_ttl_s: int = 24 * 3600,
        data_ttl_s: int = 7 * 24 * 3600,
        clock: Callable[[], float] = _wall_clock,
    ) -> None:
        self._redis = client
        self._http = http
        self._user_agent = user_agent
        self._fresh_ttl_s = fresh_ttl_s
        self._data_ttl_s = data_ttl_s
        self._clock = clock

    def get(self, domain: str, robots_url: str) -> RobotsInfo:
        """The current robots rules for ``domain``, fetching only when stale."""
        body, etag, fetched_at = self._read_cache(domain)
        now = self._clock()
        if body is not None and fetched_at is not None and now - fetched_at < self._fresh_ttl_s:
            return self._build(body, from_cache=True)

        headers = {"If-None-Match": etag} if etag else {}
        try:
            response = self._http.get(robots_url, headers=headers)
        except httpx.HTTPError:
            if body is not None:
                # Unreachable but previously seen: the stale copy is still the best
                # statement of the site's rules we have. Never treat it as absent.
                return self._build(body, from_cache=True)
            return _disallow_all()

        if response.status_code == 304 and body is not None:
            self._write_cache(domain, body=body, etag=etag, fetched_at=now)
            return self._build(body, from_cache=True)
        if response.status_code == 200:
            new_etag = response.headers.get("ETag")
            self._write_cache(domain, body=response.text, etag=new_etag, fetched_at=now)
            return self._build(response.text, from_cache=False)
        if 400 <= response.status_code < 500:
            # No robots.txt published. Cache the emptiness too — it is an answer.
            self._write_cache(domain, body="", etag=None, fetched_at=now)
            return self._build("", from_cache=False)
        if body is not None:
            return self._build(body, from_cache=True)
        return _disallow_all()

    def _build(self, body: str, *, from_cache: bool) -> RobotsInfo:
        parser = RobotFileParser()
        parser.parse(body.splitlines())
        return RobotsInfo(
            parser=parser,
            crawl_delay_s=extract_crawl_delay(body, self._user_agent),
            from_cache=from_cache,
        )

    def _read_cache(self, domain: str) -> tuple[str | None, str | None, float | None]:
        raw = self._redis.hgetall(_KEY_PREFIX + domain)
        if not isinstance(raw, dict) or not raw:
            return None, None, None
        data = {_text(k): _text(v) for k, v in raw.items()}
        fetched_at = data.get("fetched_at")
        return (
            data.get("body"),
            data.get("etag") or None,
            float(fetched_at) if fetched_at else None,
        )

    def _write_cache(self, domain: str, *, body: str, etag: str | None, fetched_at: float) -> None:
        key = _KEY_PREFIX + domain
        self._redis.hset(
            key,
            mapping={"body": body, "etag": etag or "", "fetched_at": repr(fetched_at)},
        )
        self._redis.expire(key, self._data_ttl_s)


def _text(value: object) -> str:
    """Redis values arrive as bytes or str depending on ``decode_responses``."""
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _disallow_all() -> RobotsInfo:
    parser = RobotFileParser()
    parser.parse(["User-agent: *", "Disallow: /"])
    return RobotsInfo(parser=parser, crawl_delay_s=None, from_cache=False)


def extract_crawl_delay(body: str, user_agent: str) -> float | None:
    """The ``Crawl-delay`` that applies to ``user_agent``, if the file declares one.

    :mod:`urllib.robotparser` exposes ``crawl_delay()`` but only for well-formed
    files; this extraction is explicit and forgiving because a site's stated delay
    must be honoured even when the rest of its robots.txt is sloppy. A group naming
    our agent specifically beats the ``*`` group.
    """
    ua = user_agent.lower()
    specific: float | None = None
    wildcard: float | None = None
    agents: list[str] = []
    in_group_body = False
    for raw_line in body.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if in_group_body:
                agents = []
                in_group_body = False
            agents.append(value.lower())
            continue
        in_group_body = True
        if key != "crawl-delay":
            continue
        try:
            delay = float(value)
        except ValueError:
            continue
        if delay < 0:
            continue
        for agent in agents:
            if agent == "*":
                wildcard = delay if wildcard is None else max(wildcard, delay)
            elif agent and agent in ua:
                specific = delay if specific is None else max(specific, delay)
    return specific if specific is not None else wildcard


__all__ = ["RobotsCache", "RobotsInfo", "extract_crawl_delay"]
