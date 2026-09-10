"""The personalised-pricing probe: N profiles, each a distinct session identity,
each going through the same ``run_spider_once`` path every other collection uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from apix_collector.personalisation.probe import build_profiles, run_probe
from apix_collector.quote import RawQuote
from apix_collector.spiders.base import CollectionOutcome
from apix_collector.strategies.base import FetchedPayload, SimpleResponse
from apix_core.config.watchdog import PersonalisationProbeConfig
from apix_core.models.enums import CollectionMethod, RunStatus

if TYPE_CHECKING:
    from apix_collector.session import SessionRotator

ROUTE = "DEL-BOM"
TRAVEL_DATE = date(2026, 9, 18)
ADVANCE_DAYS = 21


def _probe_config(**overrides: object) -> PersonalisationProbeConfig:
    payload: dict[str, object] = {
        "n_sessions": 4,
        "cookie_states": ["none", "existing_thin"],
        "ua_classes": ["desktop_chrome", "mobile_safari"],
        "geographies": ["in_delhi"],
        "routes": [ROUTE],
        "max_runs_per_day": 2,
        "min_interval_hours": 12.0,
    }
    payload.update(overrides)
    return PersonalisationProbeConfig.model_validate(payload)


@dataclass
class _FakeSpider:
    """Records the session rotator it was built with, so a test can inspect which
    profile actually reached ``collect()``.
    """

    source_code: str
    rotator: SessionRotator
    fare: Decimal

    def collect(
        self, *, route_code: str, travel_date: date, advance_days: int
    ) -> CollectionOutcome:
        session = self.rotator.next()
        payload = FetchedPayload(
            body=b"{}",
            response=SimpleResponse(url="http://localhost/fixtures/x", content=b"{}"),
            collection_method=CollectionMethod.PUBLIC_JSON_API,
        )
        quote = RawQuote(
            carrier_iata="6E",
            total_fare=self.fare,
            dep_datetime_local=datetime.combine(travel_date, datetime.min.time()),
        )
        # A real (non-fixture) source's fare could plausibly depend on `session`;
        # the fake here is deliberately session-independent, matching what actually
        # happens against fixture_replay today (see the module docstring).
        del session
        return CollectionOutcome(
            quotes=[quote],
            payload=payload,
            strategy_name=CollectionMethod.PUBLIC_JSON_API,
            route_code=route_code,
            travel_date=travel_date,
            query_date=travel_date,
            advance_days=advance_days,
        )


class TestBuildProfiles:
    def test_respects_n_sessions_cap(self) -> None:
        cfg = _probe_config(n_sessions=3)
        profiles = build_profiles(cfg)
        assert len(profiles) == 3

    def test_covers_the_configured_axes(self) -> None:
        cfg = _probe_config(n_sessions=4)
        profiles = build_profiles(cfg)
        assert {p.cookie_state for p in profiles} == {"none", "existing_thin"}
        assert {p.ua_class for p in profiles} <= {"desktop_chrome", "mobile_safari"}

    def test_session_ids_are_unique(self) -> None:
        cfg = _probe_config(n_sessions=4)
        profiles = build_profiles(cfg)
        assert len({p.session_id for p in profiles}) == len(profiles)


class TestRunProbe:
    def test_issues_the_identical_query_once_per_profile(self) -> None:
        cfg = _probe_config(n_sessions=4)
        profiles = build_profiles(cfg)
        built_with: list[SessionRotator] = []

        def factory(rotator: SessionRotator) -> _FakeSpider:
            built_with.append(rotator)
            return _FakeSpider("test_source", rotator, Decimal("4500.00"))

        results = run_probe(
            factory, profiles, route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=ADVANCE_DAYS
        )
        assert len(results) == len(profiles)
        assert len(built_with) == len(profiles)
        for profile, run_result in zip(profiles, results, strict=True):
            assert run_result.profile is profile
            assert run_result.result.status is RunStatus.SUCCEEDED

    def test_each_profile_gets_its_own_fixed_session_context(self) -> None:
        cfg = _probe_config(n_sessions=4)
        profiles = build_profiles(cfg)
        seen_session_ids: list[str] = []

        def factory(rotator: SessionRotator) -> _FakeSpider:
            seen_session_ids.append(rotator.next().session_id)
            return _FakeSpider("test_source", rotator, Decimal("4500.00"))

        run_probe(
            factory, profiles, route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=ADVANCE_DAYS
        )
        assert seen_session_ids == [p.session_id for p in profiles]
