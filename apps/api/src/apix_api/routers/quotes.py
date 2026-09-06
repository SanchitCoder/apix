"""/v1/quotes — the cleaned observations behind a route index value.

Audit drill-down, level 3: a route index value resolves to these rows, and each row
resolves further through ``/v1/provenance/{quote_id}``. Screened-out observations are
listed with their flags — an outlier is shown as dropped, not hidden.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from apix_api.errors import ERROR_RESPONSES
from apix_api.examples import EXAMPLE_PERIODS, EXAMPLE_QUOTE_ID, response_meta
from apix_api.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorParam,
    LimitParam,
    Page,
    PageInfo,
    encode_cursor,
    query_signature,
)
from apix_api.schemas import QuoteSummary

router = APIRouter(prefix="/v1", tags=["provenance"], responses=ERROR_RESPONSES)


@router.get(
    "/quotes",
    summary="Cleaned quotes behind a route and period",
    response_model=Page[QuoteSummary],
)
async def list_quotes(
    route: Annotated[
        str,
        Query(pattern="^[A-Z]{3}-[A-Z]{3}$", description="Route code.", examples=["DEL-BOM"]),
    ] = "DEL-BOM",
    period: Annotated[
        date, Query(description="Period the quotes contributed to.")
    ] = EXAMPLE_PERIODS[-1],
    include_screened: Annotated[
        bool,
        Query(description="Include observations dropped by outlier screens or imputation."),
    ] = True,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
) -> Page[QuoteSummary]:
    """List the observations a route index value rests on.

    The first row reuses the documented example quote id, so the drill-down to
    ``/v1/provenance/{quote_id}`` works end to end against this phase. One row is an
    outlier and one is imputed: the treatments a consumer must see are present in the
    example payload, not only in the schema.
    """
    rows = [
        QuoteSummary(
            quote_id=EXAMPLE_QUOTE_ID,
            clean_id="00000000-0000-4000-8000-000000000004",
            route_code=route,
            carrier_iata="6E",
            travel_date=date(2026, 8, 29),
            query_date=date(2026, 8, 15),
            advance_days=14,
            total_fare=5000.00,
            currency="INR",
            source_code="fixture_replay",
            is_outlier=False,
            outlier_rule=None,
            is_imputed=False,
            imputation_method=None,
        ),
        QuoteSummary(
            quote_id="00000000-0000-4000-8000-00000000000a",
            clean_id="00000000-0000-4000-8000-00000000000b",
            route_code=route,
            carrier_iata="AI",
            travel_date=date(2026, 8, 29),
            query_date=date(2026, 8, 22),
            advance_days=7,
            total_fare=7500.00,
            currency="INR",
            source_code="fixture_replay",
            is_outlier=False,
            outlier_rule=None,
            is_imputed=False,
            imputation_method=None,
        ),
        QuoteSummary(
            quote_id="00000000-0000-4000-8000-00000000000c",
            clean_id=None,
            route_code=route,
            carrier_iata="6E",
            travel_date=date(2026, 8, 29),
            query_date=date(2026, 8, 28),
            advance_days=1,
            total_fare=45000.00,
            currency="INR",
            source_code="fixture_replay",
            is_outlier=True,
            outlier_rule="log_price_mad",
            is_imputed=False,
            imputation_method=None,
        ),
        QuoteSummary(
            quote_id="00000000-0000-4000-8000-00000000000d",
            clean_id="00000000-0000-4000-8000-00000000000f",
            route_code=route,
            carrier_iata="AI",
            travel_date=date(2026, 8, 30),
            query_date=date(2026, 8, 16),
            advance_days=14,
            total_fare=5100.00,
            currency="INR",
            source_code="fixture_replay",
            is_outlier=False,
            outlier_rule=None,
            is_imputed=True,
            imputation_method="targeted_mean",
        ),
    ]
    items = rows if include_screened else [r for r in rows if not r.is_outlier]
    sig = query_signature(route=route, period=period, include_screened=include_screened)
    return Page[QuoteSummary](
        items=items,
        pagination=PageInfo(
            limit=limit,
            returned=len(items),
            has_more=False,
            next_cursor=encode_cursor({"quote_id": items[-1].quote_id}, sig),
        ),
        meta=response_meta(method_version="2026.1", basket_version="2026.1"),
    )
