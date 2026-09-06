"""Orchestration: run spiders, turn their outcomes into ``collection_run``/``fare_quote`` rows.

Split into two halves on purpose:

* :func:`run_spider_once` — pure with respect to the database. Runs one spider for one
  (route, travel_date, advance_days), and turns every outcome — success, policy
  denial, CAPTCHA, exhausted strategies, schema drift, an exhausted budget — into a
  :class:`SpiderRunResult`. This is what "never crash the sweep" means in code: none
  of those are exceptions by the time this function returns.
* :func:`persist_run_result` — takes a result and an open session and writes it. This
  is the only half that touches the database, so the classification logic above is
  testable (and tested) without one.

``collect_once`` wires both together for ``make collect-once``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from apix_collector.errors import AllStrategiesFailed, BudgetExceeded, SchemaDriftError
from apix_core.models.collection import CollectionRun, Source
from apix_core.models.enums import CollectionMethod, LegalBasis, RunStatus
from apix_core.models.quotes import FareQuote
from apix_core.models.reference import Route
from apix_core.policy import CaptchaDetected, PolicyDenied
from apix_core.provenance.hashing import sha256_hex
from apix_core.provenance.stamp import stamp

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from apix_collector.quote import RawQuote
    from apix_collector.spiders.base import BaseSpider
    from apix_collector.strategies.base import FetchedPayload
    from apix_core.provenance.store import ObjectStore


@dataclass(frozen=True, slots=True)
class SpiderRunResult:
    """The outcome of one ``spider.collect(...)`` call, classified for persistence."""

    status: RunStatus
    source_code: str
    route_code: str
    travel_date: date
    query_date: date
    advance_days: int
    quotes: list[RawQuote]
    payload: FetchedPayload | None
    collection_method: CollectionMethod | None
    error_class: str | None
    error_detail: dict[str, Any] | None
    blocked_count: int


def run_spider_once(
    spider: BaseSpider,
    *,
    route_code: str,
    travel_date: date,
    advance_days: int,
    fixture_mode: bool = True,
) -> SpiderRunResult:
    """Run one spider once. Always returns; never raises.

    ``fixture_mode`` tags a successful outcome's ``collection_method`` as ``FIXTURE``
    regardless of which acquisition strategy actually served it — true of every run
    today, since every real source in ``config/sources.yaml`` is still
    ``NOT_REVIEWED``/disabled and the only thing a spider can legally reach is the
    ``fixture_replay`` source (see ``apix_collector.fixtureserver``).
    """
    query_date = travel_date - timedelta(days=advance_days)

    def _blocked(error_class: str, detail: dict[str, Any]) -> SpiderRunResult:
        return SpiderRunResult(
            status=RunStatus.BLOCKED,
            source_code=spider.source_code,
            route_code=route_code,
            travel_date=travel_date,
            query_date=query_date,
            advance_days=advance_days,
            quotes=[],
            payload=None,
            collection_method=None,
            error_class=error_class,
            error_detail=detail,
            blocked_count=1,
        )

    def _failed(error_class: str, detail: dict[str, Any]) -> SpiderRunResult:
        return SpiderRunResult(
            status=RunStatus.FAILED,
            source_code=spider.source_code,
            route_code=route_code,
            travel_date=travel_date,
            query_date=query_date,
            advance_days=advance_days,
            quotes=[],
            payload=None,
            collection_method=None,
            error_class=error_class,
            error_detail=detail,
            blocked_count=0,
        )

    try:
        outcome = spider.collect(
            route_code=route_code, travel_date=travel_date, advance_days=advance_days
        )
    except PolicyDenied as exc:
        return _blocked("policy_denied", {"rule": exc.decision.rule, "reason": exc.decision.reason})
    except CaptchaDetected as exc:
        return _blocked("captcha", {"source": exc.source_code, "signature": exc.signature})
    except AllStrategiesFailed as exc:
        return _failed("all_strategies_failed", {"attempts": exc.attempts})
    except SchemaDriftError as exc:
        return _failed("schema_drift", {"reason": exc.reason})
    except BudgetExceeded as exc:
        return _failed("budget_exceeded", {"limit": exc.limit})

    method = CollectionMethod.FIXTURE if fixture_mode else outcome.strategy_name
    return SpiderRunResult(
        status=RunStatus.SUCCEEDED,
        source_code=spider.source_code,
        route_code=route_code,
        travel_date=outcome.travel_date,
        query_date=outcome.query_date,
        advance_days=outcome.advance_days,
        quotes=outcome.quotes,
        payload=outcome.payload,
        collection_method=method,
        error_class=None,
        error_detail=None,
        blocked_count=0,
    )


def source_id_by_code(session: Session, source_code: str) -> uuid.UUID:
    return session.execute(select(Source.id).where(Source.code == source_code)).scalar_one()


def route_id_by_code(session: Session, route_code: str, basket_version: str) -> uuid.UUID:
    return session.execute(
        select(Route.id).where(Route.code == route_code, Route.basket_version == basket_version)
    ).scalar_one()


def _quote_content_hash(
    *, source_code: str, route_code: str, query_date: date, travel_date: date, raw: RawQuote
) -> str:
    """Hash the *fare*, not the response — a search result page carries many quotes.

    ``apix_core.provenance.stamp.stamp`` hashes the raw response body, which is
    exactly right for ``source_url_hash``/``raw_payload_ref`` (many quotes really did
    come from that one response) but wrong for ``content_hash``: two different fares
    parsed out of the same page must not collide under ``uq_fare_quote_dedup``, which
    is keyed on ``(content_hash, collected_at)``. This mirrors
    ``apix_core.testing.seed._quote_content_hash`` — same idea, same field set, for a
    collected quote instead of a synthetic one.
    """
    payload = {
        "source_code": source_code,
        "route_code": route_code,
        "query_date": query_date.isoformat(),
        "travel_date": travel_date.isoformat(),
        "carrier_iata": raw.carrier_iata,
        "flight_number": raw.flight_number,
        "fare_class": raw.fare_class.value,
        "fare_brand": raw.fare_brand,
        "base_fare": str(raw.base_fare) if raw.base_fare is not None else None,
        "taxes": str(raw.taxes) if raw.taxes is not None else None,
        "udf": str(raw.udf) if raw.udf is not None else None,
        "convenience_fee": str(raw.convenience_fee) if raw.convenience_fee is not None else None,
        "total_fare": str(raw.total_fare),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256_hex(canonical.encode("utf-8"))


def persist_run_result(
    session: Session,
    *,
    source_id: uuid.UUID,
    route_id: uuid.UUID,
    result: SpiderRunResult,
    object_store: ObjectStore,
    legal_basis: LegalBasis = LegalBasis.FIXTURE,
) -> CollectionRun:
    """Write one ``collection_run`` row, plus one ``fare_quote`` row per quote.

    Every row this writes traces back to ``result``: a blocked or failed result still
    gets its ``collection_run`` row (CLAUDE.md principle 2 — an empty result is data,
    not a gap), just with no quotes attached.
    """
    run = CollectionRun(
        source_id=source_id,
        route_id=route_id,
        finished_at=datetime.now(UTC),
        status=result.status,
        quotes_collected=len(result.quotes),
        blocked_count=result.blocked_count,
        error_class=result.error_class,
        error_detail=result.error_detail,
    )
    session.add(run)
    session.flush()  # assigns run.id without committing

    for raw in result.quotes:
        assert result.payload is not None and result.collection_method is not None
        quote = FareQuote(
            run_id=run.id,
            source_id=source_id,
            collection_method=result.collection_method,
            legal_basis=legal_basis,
            route_id=route_id,
            carrier_iata=raw.carrier_iata,
            flight_number=raw.flight_number,
            dep_datetime_local=raw.dep_datetime_local,
            arr_datetime_local=raw.arr_datetime_local,
            stops=raw.stops,
            travel_date=result.travel_date,
            query_date=result.query_date,
            advance_days=result.advance_days,
            fare_class=raw.fare_class,
            fare_brand=raw.fare_brand,
            base_fare=raw.base_fare,
            taxes=raw.taxes,
            udf=raw.udf,
            convenience_fee=raw.convenience_fee,
            total_fare=raw.total_fare,
            currency=raw.currency,
            seats_shown=raw.seats_shown,
            refundable=raw.refundable,
            baggage_included=raw.baggage_included,
        )
        stamp(quote, result.payload.response, object_store)
        quote.content_hash = _quote_content_hash(
            source_code=result.source_code,
            route_code=result.route_code,
            query_date=result.query_date,
            travel_date=result.travel_date,
            raw=raw,
        )
        session.add(quote)

    return run


__all__ = [
    "SpiderRunResult",
    "persist_run_result",
    "route_id_by_code",
    "run_spider_once",
    "source_id_by_code",
]
