"""``run_spider_once``: every spider outcome becomes a result, never an exception."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from apix_collector.errors import AllStrategiesFailed, BudgetExceeded, SchemaDriftError
from apix_collector.quote import RawQuote
from apix_collector.run import run_spider_once
from apix_collector.spiders.base import CollectionOutcome
from apix_collector.strategies.base import FetchedPayload, SimpleResponse
from apix_core.models.enums import CollectionMethod, PolicyDecisionOutcome, RunStatus
from apix_core.policy import CaptchaDetected, PolicyDenied
from apix_core.policy.decisions import Decision

ROUTE = "DEL-BOM"
TRAVEL_DATE = date(2026, 9, 18)
ADVANCE_DAYS = 21


@dataclass
class _FakeSpider:
    source_code: str
    outcome_or_error: object

    def collect(self, *, route_code, travel_date, advance_days):
        if isinstance(self.outcome_or_error, BaseException):
            raise self.outcome_or_error
        return self.outcome_or_error


def _some_outcome() -> CollectionOutcome:
    payload = FetchedPayload(
        body=b"{}",
        response=SimpleResponse(url="http://localhost/fixtures/x", content=b"{}"),
        collection_method=CollectionMethod.PUBLIC_JSON_API,
    )
    quote = RawQuote(
        carrier_iata="6E",
        total_fare=Decimal("4000.00"),
        dep_datetime_local=datetime.combine(TRAVEL_DATE, datetime.min.time()),
    )
    return CollectionOutcome(
        quotes=[quote],
        payload=payload,
        strategy_name=CollectionMethod.PUBLIC_JSON_API,
        route_code=ROUTE,
        travel_date=TRAVEL_DATE,
        query_date=date(2026, 8, 28),
        advance_days=ADVANCE_DAYS,
    )


def test_success_is_tagged_fixture_by_default() -> None:
    spider = _FakeSpider("test_source", _some_outcome())
    result = run_spider_once(
        spider, route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=ADVANCE_DAYS
    )
    assert result.status is RunStatus.SUCCEEDED
    assert result.collection_method is CollectionMethod.FIXTURE
    assert len(result.quotes) == 1
    assert result.blocked_count == 0
    assert result.error_class is None


def test_success_keeps_real_method_when_not_fixture_mode() -> None:
    spider = _FakeSpider("test_source", _some_outcome())
    result = run_spider_once(
        spider,
        route_code=ROUTE,
        travel_date=TRAVEL_DATE,
        advance_days=ADVANCE_DAYS,
        fixture_mode=False,
    )
    assert result.collection_method is CollectionMethod.PUBLIC_JSON_API


def test_policy_denied_is_blocked() -> None:
    decision = Decision(
        allowed=False,
        reason="path not allowed",
        rule="disallowed_paths",
        outcome=PolicyDecisionOutcome.DENIED_PATH,
        url_hash="hash",
        source_code="test_source",
    )
    spider = _FakeSpider("test_source", PolicyDenied(decision))
    result = run_spider_once(
        spider, route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=ADVANCE_DAYS
    )
    assert result.status is RunStatus.BLOCKED
    assert result.error_class == "policy_denied"
    assert result.error_detail == {"rule": "disallowed_paths", "reason": "path not allowed"}
    assert result.blocked_count == 1
    assert result.quotes == []


def test_captcha_is_blocked() -> None:
    spider = _FakeSpider("test_source", CaptchaDetected("test_source", "recaptcha"))
    result = run_spider_once(
        spider, route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=ADVANCE_DAYS
    )
    assert result.status is RunStatus.BLOCKED
    assert result.error_class == "captcha"
    assert result.error_detail == {"source": "test_source", "signature": "recaptcha"}


def test_all_strategies_failed_is_failed_not_blocked() -> None:
    spider = _FakeSpider(
        "test_source", AllStrategiesFailed("test_source", ROUTE, ["json: 404", "rendered: 500"])
    )
    result = run_spider_once(
        spider, route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=ADVANCE_DAYS
    )
    assert result.status is RunStatus.FAILED
    assert result.error_class == "all_strategies_failed"
    assert result.error_detail == {"attempts": ["json: 404", "rendered: 500"]}
    assert result.blocked_count == 0


def test_schema_drift_is_failed() -> None:
    spider = _FakeSpider("test_source", SchemaDriftError("test_source", "field missing"))
    result = run_spider_once(
        spider, route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=ADVANCE_DAYS
    )
    assert result.status is RunStatus.FAILED
    assert result.error_class == "schema_drift"
    assert result.error_detail == {"reason": "field missing"}


def test_budget_exceeded_is_failed() -> None:
    spider = _FakeSpider("test_source", BudgetExceeded("test_source", 20))
    result = run_spider_once(
        spider, route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=ADVANCE_DAYS
    )
    assert result.status is RunStatus.FAILED
    assert result.error_class == "budget_exceeded"
    assert result.error_detail == {"limit": 20}


def test_query_date_is_derived_even_on_a_blocked_result() -> None:
    decision = Decision(
        allowed=False,
        reason="x",
        rule="tos",
        outcome=PolicyDecisionOutcome.DENIED_TOS,
        url_hash="h",
        source_code="test_source",
    )
    spider = _FakeSpider("test_source", PolicyDenied(decision))
    result = run_spider_once(spider, route_code=ROUTE, travel_date=TRAVEL_DATE, advance_days=10)
    assert result.query_date == date(2026, 9, 8)
    assert result.travel_date == TRAVEL_DATE
    assert result.advance_days == 10
