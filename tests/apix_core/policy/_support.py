"""Shared builders for PolicyEngine tests.

Everything here is offline by construction: HTTP goes through ``httpx.MockTransport``
and Redis is fakeredis. Time is a :class:`FakeClock` so every test controls it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from apix_core.config.sources import SourceEntry, SourcePolicyConfig, SourcesConfig
from apix_core.models.enums import LegalBasis, SourceType, TosVerdict
from apix_core.policy import InMemoryDecisionLog, PolicyEngine

# The instant every test starts at, unless it says otherwise.
BASE_TIME = datetime(2026, 9, 4, 12, 0, tzinfo=UTC).timestamp()
FRESH_REVIEW = datetime(2026, 8, 15, tzinfo=UTC)  # 20 days before BASE_TIME

DOMAIN = "example.test"
USER_AGENT = "APIx-Test/1.0 (+test@example.org)"

ALLOW_ALL_ROBOTS = "User-agent: *\nAllow: /\n"


class FakeClock:
    def __init__(self, start: float = BASE_TIME) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_policy(**overrides) -> SourcePolicyConfig:
    values = {
        "robots_url": f"https://{DOMAIN}/robots.txt",
        "allowed_paths": ["/fares/"],
        "disallowed_paths": ["/booking/"],
        "crawl_delay_s": 0.0,
        "max_requests_per_hour": 1000,
        "tos_url": f"https://{DOMAIN}/tos",
        "tos_reviewed_at": FRESH_REVIEW,
        "tos_verdict": TosVerdict.PERMITTED,
        "legal_basis": LegalBasis.ROBOTS_ALLOWED,
    }
    values.update(overrides)
    return SourcePolicyConfig(**values)


def make_source(
    code: str = "test_source", *, enabled: bool = True, **policy_overrides
) -> SourceEntry:
    return SourceEntry(
        code=code,
        display_name="Test source",
        domain=policy_overrides.pop("domain", DOMAIN),
        source_type=SourceType.OTA,
        enabled=enabled,
        policy=make_policy(**policy_overrides),
    )


def make_config(*sources: SourceEntry) -> SourcesConfig:
    return SourcesConfig(version="test", sources=list(sources or [make_source()]))


class RecordingHandler:
    """A MockTransport handler that counts calls and serves robots + fares."""

    def __init__(self, robots_body: str = ALLOW_ALL_ROBOTS) -> None:
        self.robots_body = robots_body
        self.requests: list[httpx.Request] = []
        self.responses: dict[str, httpx.Response] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=self.robots_body, headers={"ETag": '"v1"'})
        if path in self.responses:
            return self.responses[path]
        return httpx.Response(200, text="<html><body>fare 4999 INR</body></html>")

    @property
    def non_robots_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path != "/robots.txt"]


def build_engine(
    fake_redis,
    *,
    config: SourcesConfig | None = None,
    handler: RecordingHandler | None = None,
    clock: FakeClock | None = None,
    log: InMemoryDecisionLog | None = None,
    **engine_kwargs,
) -> tuple[PolicyEngine, RecordingHandler, FakeClock, InMemoryDecisionLog]:
    handler = handler if handler is not None else RecordingHandler()
    clock = clock if clock is not None else FakeClock()
    log = log if log is not None else InMemoryDecisionLog()
    engine = PolicyEngine(
        config=config if config is not None else make_config(),
        redis_client=fake_redis,
        decision_log=log,
        user_agent=USER_AGENT,
        transport=httpx.MockTransport(handler),
        clock=clock,
        **engine_kwargs,
    )
    return engine, handler, clock, log
