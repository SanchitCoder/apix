"""BaseSpider's contract: retries, strategy fallback, session rotation, budget.

Uses scripted fake strategies rather than the real ones — this file is about the
contract ``BaseSpider`` enforces on top of *any* strategy, not about a specific
source's fetching. See ``tests/collector/spiders/test_indigo.py`` and friends for the
concrete spiders against real fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import pytest

from apix_collector.backoff import Backoff
from apix_collector.budget import RunBudget
from apix_collector.errors import AllStrategiesFailed, BudgetExceeded, FetchFailed
from apix_collector.quote import RawQuote
from apix_collector.session import SessionRotator
from apix_collector.spiders.base import BaseSpider
from apix_collector.strategies.base import FetchedPayload, SimpleResponse
from apix_core.models.enums import CollectionMethod

ROUTE = "DEL-BOM"
TRAVEL_DATE = date(2026, 9, 18)
ADVANCE_DAYS = 21

SOME_QUOTE = RawQuote(
    carrier_iata="6E",
    total_fare=Decimal("4000.00"),
    dep_datetime_local=datetime.combine(TRAVEL_DATE, datetime.min.time()),
)


@dataclass
class ScriptedStrategy:
    """A strategy whose ``fetch()`` outcomes are scripted in advance."""

    name: CollectionMethod
    outcomes: list[object]  # FetchedPayload instances or exceptions, consumed in order
    calls: list[str] = field(default_factory=list)

    def fetch(self, *, policy_engine, url, session):
        self.calls.append(url)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _payload(body: bytes = b"{}") -> FetchedPayload:
    return FetchedPayload(
        body=body,
        response=SimpleResponse(url="http://example.test/x", content=body),
        collection_method=CollectionMethod.PUBLIC_JSON_API,
    )


@dataclass
class FakeMapper:
    source_code: str = "test_source"
    quotes: list[RawQuote] = field(default_factory=lambda: [SOME_QUOTE])

    def parse(self, payload, context):
        return self.quotes


class _Spider(BaseSpider):
    source_code = "test_source"

    def build_url(self, strategy, *, route_code, travel_date, query_date):
        return f"http://example.test/{strategy.name.value}/{route_code}"


def _make_spider(strategies, **kwargs) -> _Spider:
    return _Spider(
        mapper=FakeMapper(),
        strategies=strategies,
        policy_engine=object(),  # never touched by ScriptedStrategy
        backoff=Backoff(sleep=lambda _s: None),  # never actually sleep in tests
        **kwargs,
    )


def test_first_successful_strategy_wins_and_later_ones_are_never_tried() -> None:
    first = ScriptedStrategy(CollectionMethod.PUBLIC_JSON_API, [_payload(b"first")])
    second = ScriptedStrategy(CollectionMethod.RENDERED_PAGE, [_payload(b"second")])
    outcome = _make_spider([first, second]).collect(
        route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=ADVANCE_DAYS
    )
    assert outcome.payload.body == b"first"
    assert outcome.strategy_name is CollectionMethod.PUBLIC_JSON_API
    assert outcome.quotes == [SOME_QUOTE]
    assert second.calls == []


def test_query_date_and_advance_days_are_computed_correctly() -> None:
    strategy = ScriptedStrategy(CollectionMethod.PUBLIC_JSON_API, [_payload()])
    outcome = _make_spider([strategy]).collect(
        route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=ADVANCE_DAYS
    )
    assert outcome.query_date == date(2026, 8, 28)
    assert outcome.travel_date == TRAVEL_DATE
    assert outcome.advance_days == ADVANCE_DAYS


def test_non_retryable_failure_falls_back_to_the_next_strategy() -> None:
    first = ScriptedStrategy(CollectionMethod.PUBLIC_JSON_API, [FetchFailed(404, "u")])
    second = ScriptedStrategy(CollectionMethod.RENDERED_PAGE, [_payload(b"fallback")])
    outcome = _make_spider([first, second]).collect(
        route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=ADVANCE_DAYS
    )
    assert outcome.payload.body == b"fallback"
    assert len(first.calls) == 1  # a 404 is never retried


def test_retryable_failure_is_retried_before_falling_back() -> None:
    first = ScriptedStrategy(
        CollectionMethod.PUBLIC_JSON_API,
        [FetchFailed(503, "u"), _payload(b"succeeded-on-retry")],
    )
    outcome = _make_spider([first], retries=1).collect(
        route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=ADVANCE_DAYS
    )
    assert outcome.payload.body == b"succeeded-on-retry"
    assert len(first.calls) == 2


def test_retries_exhausted_falls_back_to_the_next_strategy() -> None:
    first = ScriptedStrategy(
        CollectionMethod.PUBLIC_JSON_API, [FetchFailed(500, "u"), FetchFailed(500, "u")]
    )
    second = ScriptedStrategy(CollectionMethod.RENDERED_PAGE, [_payload(b"fallback")])
    outcome = _make_spider([first, second], retries=1).collect(
        route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=ADVANCE_DAYS
    )
    assert outcome.payload.body == b"fallback"
    assert len(first.calls) == 2  # one original attempt + one retry, then gave up


def test_all_strategies_failing_raises_all_strategies_failed() -> None:
    first = ScriptedStrategy(CollectionMethod.PUBLIC_JSON_API, [FetchFailed(404, "u")])
    second = ScriptedStrategy(CollectionMethod.RENDERED_PAGE, [FetchFailed(500, "u")])
    with pytest.raises(AllStrategiesFailed) as excinfo:
        _make_spider([first, second], retries=0).collect(
            route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=ADVANCE_DAYS
        )
    assert excinfo.value.source_code == "test_source"
    assert len(excinfo.value.attempts) == 2


def test_budget_exhaustion_propagates() -> None:
    strategy = ScriptedStrategy(
        CollectionMethod.PUBLIC_JSON_API, [FetchFailed(500, "u"), FetchFailed(500, "u")]
    )
    budget = RunBudget("test_source", 1)
    with pytest.raises(BudgetExceeded):
        _make_spider([strategy], retries=3, budget=budget).collect(
            route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=ADVANCE_DAYS
        )
    assert len(strategy.calls) == 1  # the second attempt never got a request out


def test_session_rotates_across_retries() -> None:
    seen_sessions: list[str] = []

    class RecordingStrategy(ScriptedStrategy):
        def fetch(self, *, policy_engine, url, session):
            seen_sessions.append(session.session_id)
            return super().fetch(policy_engine=policy_engine, url=url, session=session)

    strategy = RecordingStrategy(
        CollectionMethod.PUBLIC_JSON_API, [FetchFailed(500, "u"), _payload()]
    )
    _make_spider([strategy], retries=1, session_rotator=SessionRotator(pool_size=2)).collect(
        route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=ADVANCE_DAYS
    )
    assert len(set(seen_sessions)) == 2


def test_at_least_one_strategy_is_required() -> None:
    with pytest.raises(ValueError, match="at least one strategy"):
        _make_spider([])


def test_advance_days_out_of_range_is_rejected() -> None:
    strategy = ScriptedStrategy(CollectionMethod.PUBLIC_JSON_API, [_payload()])
    with pytest.raises(ValueError, match="advance_days"):
        _make_spider([strategy]).collect(
            route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=400
        )
