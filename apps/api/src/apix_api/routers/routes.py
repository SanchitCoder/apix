"""/v1/routes — the basket, and per-route fare series."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Path, Query

from apix_api.errors import ERROR_RESPONSES
from apix_api.examples import EXAMPLE_PERIODS, example_offset, response_meta
from apix_api.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorParam,
    LimitParam,
    Page,
    PageInfo,
    encode_cursor,
    query_signature,
)
from apix_api.schemas import RouteSeriesPoint, RouteSummary

router = APIRouter(prefix="/v1", tags=["routes"], responses=ERROR_RESPONSES)

RouteCodePath = Annotated[
    str,
    Path(
        pattern="^[A-Z]{3}-[A-Z]{3}$",
        description="Directional route code, e.g. DEL-BOM.",
        examples=["DEL-BOM"],
    ),
]


@router.get("/routes", summary="Routes in the current basket", response_model=Page[RouteSummary])
async def list_routes(
    basket_version: Annotated[
        str | None, Query(description="Defaults to the basket in force today.")
    ] = None,
    active_on: Annotated[date | None, Query(description="Only routes active on this date.")] = None,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
) -> Page[RouteSummary]:
    """List the basket.

    ``dgca_pax_share`` is null on every route until Phase 2 loads the DGCA release. That
    null is the honest answer, not a missing field.
    """
    # Coordinates are reference data from db/seeds/airports.csv (OurAirports, CC0),
    # not placeholders — the corridor map cannot be drawn from invented positions.
    airports = {
        "DEL": ("Delhi", 28.555630, 77.095190),
        "BOM": ("Mumbai", 19.088699, 72.867897),
        "BLR": ("Bengaluru", 13.197900, 77.706299),
    }
    pairs = [("DEL", "BOM"), ("BOM", "DEL"), ("DEL", "BLR"), ("BLR", "DEL")]
    items = []
    for origin, dest in pairs:
        origin_city, origin_lat, origin_lon = airports[origin]
        dest_city, dest_lat, dest_lon = airports[dest]
        items.append(
            RouteSummary(
                code=f"{origin}-{dest}",
                origin_iata=origin,
                origin_city=origin_city,
                dest_iata=dest,
                dest_city=dest_city,
                dgca_pax_share=None,
                basket_version="2026.1",
                active_from=date(2026, 1, 1),
                active_to=None,
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                dest_lat=dest_lat,
                dest_lon=dest_lon,
            )
        )
    sig = query_signature(basket_version=basket_version, active_on=active_on)
    return Page[RouteSummary](
        items=items,
        pagination=PageInfo(
            limit=limit,
            returned=len(items),
            has_more=True,
            next_cursor=encode_cursor({"code": items[-1].code}, sig),
        ),
        meta=response_meta(basket_version="2026.1", with_run=False),
    )


@router.get(
    "/routes/{code}/series",
    summary="Fare series for one route",
    response_model=Page[RouteSeriesPoint],
)
async def get_route_series(
    code: RouteCodePath,
    advance_days: Annotated[
        int | None,
        Query(ge=0, le=365, description="Restrict to one advance-purchase lead time."),
    ] = None,
    carrier: Annotated[
        str | None,
        Query(
            pattern="^[A-Z0-9]{2}$",
            description="Restrict to one carrier (IATA designator). Omit for all carriers.",
        ),
    ] = None,
    from_: Annotated[date | None, Query(alias="from", description="Inclusive start.")] = None,
    to: Annotated[date | None, Query(description="Inclusive end.")] = None,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
) -> Page[RouteSeriesPoint]:
    """Return the fare distribution for one route over time.

    Quartiles are returned alongside the mean because an airfare distribution is
    right-skewed: the mean alone misrepresents what a traveller pays.

    The example payload varies deterministically with ``advance_days`` and ``carrier``
    so a chart split by either draws distinct, stable lines; a shorter lead time prices
    higher, as the real curve will. The final period is served ``sold_out`` so the
    front end's shading has something honest to shade.
    """
    lead = advance_days if advance_days is not None else 14
    # Walk-up fares price highest; the premium tapers with lead time.
    lead_premium = max(0.0, (60 - lead) * 25.0)
    carrier_shift = 0.0 if carrier is None else example_offset("route-series", carrier, scale=200)
    base = 5000.0 + lead_premium + carrier_shift
    items = [
        RouteSeriesPoint(
            period=period,
            advance_days=lead,
            carrier_iata=carrier,
            mean_fare=round(base + example_offset("fare", code, str(period), scale=150), 0),
            median_fare=round(base * 0.96, 0),
            p25_fare=round(base * 0.8, 0),
            p75_fare=round(base * 1.2, 0),
            n_quotes=250,
            sold_out=period == EXAMPLE_PERIODS[-1] and lead <= 3,
            currency="INR",
        )
        for period in EXAMPLE_PERIODS
    ]
    sig = query_signature(code=code, advance_days=advance_days, carrier=carrier, from_=from_, to=to)
    return Page[RouteSeriesPoint](
        items=items,
        pagination=PageInfo(
            limit=limit,
            returned=len(items),
            has_more=False,
            next_cursor=encode_cursor({"period": str(items[-1].period)}, sig),
        ),
        meta=response_meta(method_version="2026.1", basket_version="2026.1"),
    )
