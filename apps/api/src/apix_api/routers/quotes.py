"""/v1/quotes — the cleaned observations behind a route index value.

Audit drill-down, level 3: a route index value resolves to these rows, and each row
resolves further through ``/v1/provenance/{quote_id}``. Screened-out observations are
listed with their flags — an outlier is shown as dropped, not hidden. Microdata:
requires a researcher or official API key.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from apix_api.auth import require_authenticated
from apix_api.db import SessionDep  # noqa: TC001
from apix_api.errors import MICRODATA_ERROR_RESPONSES
from apix_api.meta import build_meta
from apix_api.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorParam,
    LimitParam,
    Page,
    paginate_in_memory,
    query_signature,
)
from apix_api.schemas import QuoteSummary
from apix_core.models import FareQuote, FareQuoteClean, Route, Source

router = APIRouter(
    prefix="/v1",
    tags=["provenance"],
    responses=MICRODATA_ERROR_RESPONSES,
    dependencies=[Depends(require_authenticated)],
)


@router.get(
    "/quotes",
    summary="Cleaned quotes behind a route and period",
    response_model=Page[QuoteSummary],
)
async def list_quotes(
    session: SessionDep,
    route: Annotated[
        str,
        Query(pattern="^[A-Z]{3}-[A-Z]{3}$", description="Route code.", examples=["DEL-BOM"]),
    ] = "DEL-BOM",
    period: Annotated[date, Query(description="Period the quotes contributed to.")] = date(
        2026, 8, 1
    ),
    include_screened: Annotated[
        bool,
        Query(description="Include observations dropped by outlier screens or imputation."),
    ] = True,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
) -> Page[QuoteSummary]:
    """List the observations a route index value rests on."""
    route_id = (
        await session.execute(select(Route.id).where(Route.code == route))
    ).scalar_one_or_none()
    if route_id is None:
        raise HTTPException(status_code=404, detail=f"no route with code {route!r}")

    # fare_quote_clean does not itself carry source_id (it is the analysis-ready,
    # source-agnostic row); resolve source_code through the raw quote it derives
    # from, when it derives from one at all — an imputed row has none.
    query_date_expr = FareQuoteClean.travel_date - FareQuoteClean.advance_days
    stmt = (
        select(FareQuoteClean, Source.code)
        .outerjoin(FareQuote, FareQuote.id == FareQuoteClean.quote_id)
        .outerjoin(Source, Source.id == FareQuote.source_id)
        .where(FareQuoteClean.route_id == route_id, query_date_expr == period)
        .order_by(FareQuoteClean.id)
    )
    if not include_screened:
        stmt = stmt.where(~FareQuoteClean.is_outlier)
    rows = (await session.execute(stmt)).all()

    items = [
        QuoteSummary(
            # An imputed row has no fare_quote.id (nothing was collected). QuoteSummary
            # requires a quote_id string, so clean.id stands in — is_imputed=True and a
            # distinct clean_id both mark it as not a real /v1/provenance key.
            quote_id=str(clean.quote_id) if clean.quote_id else str(clean.id),
            clean_id=str(clean.id),
            route_code=route,
            carrier_iata=clean.carrier_iata,
            travel_date=clean.travel_date,
            query_date=clean.travel_date - timedelta(days=clean.advance_days),
            advance_days=clean.advance_days,
            total_fare=float(clean.total_fare),
            currency="INR",
            source_code=source_code or "imputed",
            is_outlier=clean.is_outlier,
            outlier_rule=clean.outlier_rule,
            is_imputed=clean.is_imputed,
            imputation_method=clean.imputation_method,
        )
        for clean, source_code in rows
    ]

    sig = query_signature(route=route, period=period, include_screened=include_screened)
    page_items, page_info = paginate_in_memory(
        items,
        cursor=cursor,
        limit=limit,
        query_sig=sig,
        position_of=lambda q: {"quote_id": q.quote_id},
    )
    return Page[QuoteSummary](
        items=page_items, pagination=page_info, meta=build_meta(data_status="PUBLISHED")
    )
