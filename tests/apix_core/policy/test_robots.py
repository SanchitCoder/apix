"""RobotsCache: Redis caching, ETag revalidation, and crawl-delay extraction."""

from __future__ import annotations

import httpx
import pytest

from apix_core.policy.robots import RobotsCache, extract_crawl_delay
from tests.apix_core.policy._support import DOMAIN, USER_AGENT, FakeClock

ROBOTS_URL = f"https://{DOMAIN}/robots.txt"
ROBOTS_BODY = "User-agent: *\nDisallow: /private/\nCrawl-delay: 7\n"


class RobotsServer:
    """Serves one robots.txt with ETag semantics, counting what it sees."""

    def __init__(self, body: str = ROBOTS_BODY, etag: str = '"v1"', status: int = 200) -> None:
        self.body = body
        self.etag = etag
        self.status = status
        self.calls = 0
        self.conditional_hits = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.status != 200:
            return httpx.Response(self.status)
        if request.headers.get("If-None-Match") == self.etag:
            self.conditional_hits += 1
            return httpx.Response(304)
        return httpx.Response(200, text=self.body, headers={"ETag": self.etag})


def make_cache(fake_redis, server, clock=None):
    clock = clock or FakeClock()
    http = httpx.Client(transport=httpx.MockTransport(server))
    return RobotsCache(fake_redis, http, user_agent=USER_AGENT, clock=clock), clock


def test_fresh_cache_serves_without_refetching(fake_redis):
    server = RobotsServer()
    cache, _ = make_cache(fake_redis, server)
    first = cache.get(DOMAIN, ROBOTS_URL)
    second = cache.get(DOMAIN, ROBOTS_URL)
    assert server.calls == 1
    assert not first.from_cache
    assert second.from_cache
    assert not second.allows(USER_AGENT, f"https://{DOMAIN}/private/x")
    assert second.allows(USER_AGENT, f"https://{DOMAIN}/fares/x")
    assert second.crawl_delay_s == 7.0


def test_stale_cache_revalidates_with_etag_and_reuses_on_304(fake_redis):
    server = RobotsServer()
    cache, clock = make_cache(fake_redis, server)
    cache.get(DOMAIN, ROBOTS_URL)
    clock.advance(24 * 3600 + 1)
    info = cache.get(DOMAIN, ROBOTS_URL)
    assert server.calls == 2
    assert server.conditional_hits == 1
    assert info.from_cache  # body came from Redis, not the wire
    assert not info.allows(USER_AGENT, f"https://{DOMAIN}/private/x")
    # The 304 restarted the freshness window: no fetch within the next 24h.
    clock.advance(23 * 3600)
    cache.get(DOMAIN, ROBOTS_URL)
    assert server.calls == 2


def test_changed_robots_replaces_the_cached_rules(fake_redis):
    server = RobotsServer()
    cache, clock = make_cache(fake_redis, server)
    cache.get(DOMAIN, ROBOTS_URL)
    server.body = "User-agent: *\nDisallow: /\n"
    server.etag = '"v2"'
    clock.advance(24 * 3600 + 1)
    info = cache.get(DOMAIN, ROBOTS_URL)
    assert not info.from_cache
    assert not info.allows(USER_AGENT, f"https://{DOMAIN}/fares/x")


def test_missing_robots_file_allows_everything_and_is_cached(fake_redis):
    server = RobotsServer(status=404)
    cache, _ = make_cache(fake_redis, server)
    info = cache.get(DOMAIN, ROBOTS_URL)
    assert info.allows(USER_AGENT, f"https://{DOMAIN}/anything")
    cache.get(DOMAIN, ROBOTS_URL)
    assert server.calls == 1  # the absence is an answer, and it is cached too


def test_server_error_disallows_everything(fake_redis):
    server = RobotsServer(status=503)
    cache, _ = make_cache(fake_redis, server)
    info = cache.get(DOMAIN, ROBOTS_URL)
    assert not info.allows(USER_AGENT, f"https://{DOMAIN}/fares/x")


def test_transport_error_without_cache_disallows_everything(fake_redis):
    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    cache, _ = make_cache(fake_redis, explode)
    info = cache.get(DOMAIN, ROBOTS_URL)
    assert not info.allows(USER_AGENT, f"https://{DOMAIN}/fares/x")


def test_transport_error_with_stale_cache_reuses_the_stale_copy(fake_redis):
    server = RobotsServer()
    cache, clock = make_cache(fake_redis, server)
    cache.get(DOMAIN, ROBOTS_URL)
    server.status = 0  # now unreachable

    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    cache._http = httpx.Client(transport=httpx.MockTransport(explode))
    clock.advance(25 * 3600)
    info = cache.get(DOMAIN, ROBOTS_URL)
    assert info.from_cache
    assert not info.allows(USER_AGENT, f"https://{DOMAIN}/private/x")


def test_server_error_with_stale_cache_reuses_the_stale_copy(fake_redis):
    server = RobotsServer()
    cache, clock = make_cache(fake_redis, server)
    cache.get(DOMAIN, ROBOTS_URL)
    server.status = 500
    clock.advance(25 * 3600)
    info = cache.get(DOMAIN, ROBOTS_URL)
    assert info.from_cache
    assert not info.allows(USER_AGENT, f"https://{DOMAIN}/private/x")


# --------------------------------------------------- crawl-delay extraction ----


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("User-agent: *\nCrawl-delay: 5\n", 5.0),
        ("User-agent: *\nCrawl-delay: 2.5\n", 2.5),
        ("User-agent: *\nDisallow: /x\n", None),
        ("", None),
        # Our agent's group beats the wildcard group.
        ("User-agent: APIx-Test\nCrawl-delay: 30\n\nUser-agent: *\nCrawl-delay: 5\n", 30.0),
        # A group listing several agents applies to all of them.
        ("User-agent: googlebot\nUser-agent: APIx-Test\nCrawl-delay: 12\n", 12.0),
        # Unparseable and negative values are ignored, not errors.
        ("User-agent: *\nCrawl-delay: soon\n", None),
        ("User-agent: *\nCrawl-delay: -3\n", None),
        # Comments and stray whitespace are tolerated.
        ("User-agent: * # everyone\n Crawl-delay : 9 \n", 9.0),
        # Another agent's delay does not apply to us.
        ("User-agent: googlebot\nCrawl-delay: 60\n", None),
        # The strictest matching wildcard group wins.
        ("User-agent: *\nCrawl-delay: 3\n\nUser-agent: *\nCrawl-delay: 8\n", 8.0),
    ],
)
def test_extract_crawl_delay(body, expected):
    assert extract_crawl_delay(body, USER_AGENT) == expected
