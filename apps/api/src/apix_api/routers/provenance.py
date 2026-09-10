"""/v1/provenance/{quote_id} — the audit trail for a single observation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy import select

from apix_api.auth import require_authenticated
from apix_api.errors import MICRODATA_ERROR_RESPONSES
from apix_api.meta import build_meta
from apix_api.schemas import ProvenanceResponse, ProvenanceSource, ProvenanceTreatment
from apix_core.models import FareQuote, FareQuoteClean, IndexValueQuote, Route, Series, SourcePolicy
from apix_core.provenance.resolve import ProvenanceChain, resolve
from apix_core.provenance.store import ProvenanceError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

router = APIRouter(
    prefix="/v1",
    tags=["provenance"],
    responses=MICRODATA_ERROR_RESPONSES,
    dependencies=[Depends(require_authenticated)],
)


@dataclass(frozen=True)
class _FullChain:
    chain: ProvenanceChain
    route_code: str
    carrier_iata: str
    travel_date: date
    advance_days: int
    total_fare: Decimal
    currency: str
    tos_verdict: str | None
    tos_reviewed_at: datetime | None
    robots_fetched_at: datetime | None
    treatment: ProvenanceTreatment | None
    contributed_to: list[str]


def _resolve_full(session: Session, quote_id: uuid.UUID) -> _FullChain | None:
    """Everything ``/v1/provenance`` needs, in one sync-session round trip.

    Wraps :func:`apix_core.provenance.resolve.resolve` (Phase-1 code, untouched) with
    the extra joins the API response carries that the resolver itself does not: the
    route code, the source's ToS/robots record, the cleaning treatment and the
    index_value_quote lineage.
    """
    try:
        chain = resolve(session, quote_id)
    except ProvenanceError:
        return None

    quote_row = session.execute(
        select(
            FareQuote.carrier_iata,
            FareQuote.travel_date,
            FareQuote.advance_days,
            FareQuote.total_fare,
            FareQuote.currency,
            Route.code,
        )
        .join(Route, Route.id == FareQuote.route_id)
        .where(FareQuote.id == quote_id)
    ).one()
    carrier_iata, travel_date, advance_days, total_fare, currency, route_code = quote_row

    policy = session.get(SourcePolicy, chain.source.id)

    clean_row = session.execute(
        select(FareQuoteClean).where(FareQuoteClean.quote_id == quote_id)
    ).scalar_one_or_none()
    treatment = (
        ProvenanceTreatment(
            clean_id=str(clean_row.id),
            is_outlier=clean_row.is_outlier,
            outlier_rule=clean_row.outlier_rule,
            is_imputed=clean_row.is_imputed,
            imputation_method=clean_row.imputation_method,
            quality_vector=dict(clean_row.quality_vector),
        )
        if clean_row is not None
        else None
    )

    contributed_to: list[str] = []
    if clean_row is not None:
        lineage_rows = session.execute(
            select(Series.code, IndexValueQuote.period)
            .join(IndexValueQuote, IndexValueQuote.series_id == Series.id)
            .where(IndexValueQuote.clean_id == clean_row.id)
        ).all()
        contributed_to = sorted(f"{code}:{period.isoformat()}" for code, period in lineage_rows)

    return _FullChain(
        chain=chain,
        route_code=route_code,
        carrier_iata=carrier_iata,
        travel_date=travel_date,
        advance_days=advance_days,
        total_fare=total_fare,
        currency=currency,
        tos_verdict=policy.tos_verdict.value if policy is not None else None,
        tos_reviewed_at=policy.tos_reviewed_at if policy is not None else None,
        robots_fetched_at=policy.robots_fetched_at if policy is not None else None,
        treatment=treatment,
        contributed_to=contributed_to,
    )


@router.get(
    "/provenance/{quote_id}",
    summary="Full audit trail for one fare quote",
    response_model=ProvenanceResponse,
)
async def get_provenance(
    request: Request,
    quote_id: Annotated[uuid.UUID, Path(description="fare_quote.id")],
) -> ProvenanceResponse:
    """Resolve a quote back to its source, legal basis, cleaning and index contribution.

    This is principle 1 made operational. Every published index value is resolvable to
    the quotes behind it, and every quote is resolvable through this endpoint to the
    source it came from, the moment it was observed and the legal basis on which it was
    collected. If this endpoint cannot answer for a quote, that quote should not have
    contributed to a published number.

    Microdata: requires a researcher or official API key.
    """
    session_factory: sessionmaker[Session] = request.app.state.sync_session_factory

    def _work() -> _FullChain | None:
        with session_factory() as session:
            return _resolve_full(session, quote_id)

    result = await anyio.to_thread.run_sync(_work)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"no resolvable provenance for quote {quote_id}"
        )

    chain = result.chain
    query_date = result.travel_date - timedelta(days=result.advance_days)
    policy_decision = (
        chain.policy_decision.decision.value
        if chain.policy_decision is not None
        # No PolicyEngine decision on record (e.g. a FIXTURE/SYNTHETIC quote replayed
        # outside a live engine run): report the legal basis that stands in for it
        # rather than leaving a required field empty.
        else chain.quote.legal_basis.value
    )

    return ProvenanceResponse(
        quote_id=str(chain.quote.id),
        collected_at=chain.quote.collected_at.isoformat(),
        run_id=str(chain.run.id),
        route_code=result.route_code,
        carrier_iata=result.carrier_iata,
        travel_date=result.travel_date,
        query_date=query_date,
        advance_days=result.advance_days,
        total_fare=float(result.total_fare),
        currency=result.currency,
        source_url_hash=chain.quote.source_url_hash,
        content_hash=chain.quote.content_hash,
        raw_payload_ref=chain.raw_payload_ref,
        source=ProvenanceSource(
            source_code=chain.source.code,
            display_name=chain.source.display_name,
            domain=chain.source.domain,
            source_type=chain.source.source_type.value,
            collection_method=chain.quote.collection_method.value,
            legal_basis=chain.quote.legal_basis.value,
            policy_decision=policy_decision,
            robots_fetched_at=(
                result.robots_fetched_at.isoformat() if result.robots_fetched_at else None
            ),
            tos_verdict=result.tos_verdict or "NOT_REVIEWED",
            tos_reviewed_at=(
                result.tos_reviewed_at.isoformat() if result.tos_reviewed_at else None
            ),
        ),
        treatment=result.treatment,
        contributed_to=result.contributed_to,
        meta=build_meta(data_status="PUBLISHED"),
    )
