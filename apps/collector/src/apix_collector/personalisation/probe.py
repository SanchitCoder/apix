"""The personalised-pricing probe: issue the identical query through N session
profiles varying cookie state, UA class and geography, near-simultaneously.

Reuses :func:`apix_collector.run.run_spider_once` verbatim for the actual collection —
the same ``PolicyEngine``-gated path every other collection in this repo uses — via a
spider instance constructed with a session rotator fixed to one profile's identity.
Geography is honestly a header-only simulation (``Accept-Language``), consistent with
:mod:`apix_collector.session`'s own documented scope: real geo-IP proxying is out of
scope. Against the only enabled source today (``fixture_replay``, a static recorded
response), every profile legitimately receives an identical fare — a probe run today
correctly reports zero dispersion, not a fabricated one; the probe itself is real and
would detect real personalisation the moment it runs against a source whose fares
actually vary by session. See docs/personalisation-probe.md for the full method and
its limitations.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from apix_collector.run import run_spider_once
from apix_collector.session import SessionContext, SessionRotator

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from apix_collector.run import SpiderRunResult
    from apix_collector.spiders.base import BaseSpider
    from apix_core.config.watchdog import PersonalisationProbeConfig

# Small, honest header lookups — enough to make each profile a genuinely distinct
# request, not a claim of real device/browser fingerprinting.
_UA_STRINGS: dict[str, str] = {
    "desktop_chrome": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0 Safari/537.36",
    "mobile_safari": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) Version/17.5 Mobile Safari/604.1"
    ),
}
_GEOGRAPHY_ACCEPT_LANGUAGE: dict[str, str] = {
    "in_delhi": "en-IN,hi-IN;q=0.8",
    "in_mumbai": "en-IN,mr-IN;q=0.8",
}
_COOKIE_STATE_VALUE: dict[str, str] = {
    "none": "",
    "existing_thin": "apix_probe_visits=1",
    "existing_thick": "apix_probe_visits=6; apix_probe_last_search=DEL-BOM",
}


class _FixedProfileRotator(SessionRotator):
    """A session rotator that always returns the same, pre-built profile identity."""

    def __init__(self, context: SessionContext) -> None:
        super().__init__(pool_size=1)
        self._context = context

    def next(self) -> SessionContext:
        return self._context


@dataclass(frozen=True, slots=True)
class SessionProfile:
    """One of the N session identities the probe issues the query through."""

    session_id: str
    cookie_state: str
    ua_class: str
    geography: str

    def to_session_context(self) -> SessionContext:
        headers: dict[str, str] = {"X-APIx-Session": self.session_id}
        if self.ua_class in _UA_STRINGS:
            headers["User-Agent"] = _UA_STRINGS[self.ua_class]
        if self.geography in _GEOGRAPHY_ACCEPT_LANGUAGE:
            headers["Accept-Language"] = _GEOGRAPHY_ACCEPT_LANGUAGE[self.geography]
        cookie = _COOKIE_STATE_VALUE.get(self.cookie_state, "")
        if cookie:
            headers["Cookie"] = cookie
        return SessionContext(session_id=self.session_id, headers=MappingProxyType(headers))


def build_profiles(cfg: PersonalisationProbeConfig) -> list[SessionProfile]:
    """Up to ``cfg.n_sessions`` profiles spanning cookie_state x ua_class x
    geography, in a fixed, deterministic order — so a probe run is reproducible.
    """
    combinations = (
        (str(cookie_state), ua_class, geography)
        for cookie_state in cfg.cookie_states
        for ua_class in cfg.ua_classes
        for geography in cfg.geographies
    )
    profiles = [
        SessionProfile(session_id=f"probe-{i:02d}", cookie_state=cs, ua_class=ua, geography=geo)
        for i, (cs, ua, geo) in enumerate(combinations)
    ]
    return profiles[: cfg.n_sessions]


@dataclass(frozen=True, slots=True)
class ProfileRunResult:
    """One profile's outcome for one probe instance."""

    profile: SessionProfile
    result: SpiderRunResult


def run_probe(
    spider_factory: Callable[[SessionRotator], BaseSpider],
    profiles: list[SessionProfile],
    *,
    route_code: str,
    travel_date: date,
    advance_days: int,
) -> list[ProfileRunResult]:
    """Issue the identical query once per profile, each through its own fixed
    session identity. Every call goes through :func:`apix_collector.run.run_spider_once`
    — the spider's own ``PolicyEngine`` — exactly like ordinary collection; nothing
    here bypasses it.
    """
    results: list[ProfileRunResult] = []
    for profile in profiles:
        spider = spider_factory(_FixedProfileRotator(profile.to_session_context()))
        result = run_spider_once(
            spider, route_code=route_code, travel_date=travel_date, advance_days=advance_days
        )
        results.append(ProfileRunResult(profile=profile, result=result))
    return results


__all__ = ["ProfileRunResult", "SessionProfile", "build_profiles", "run_probe"]
