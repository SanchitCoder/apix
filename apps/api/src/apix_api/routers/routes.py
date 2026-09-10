"""/v1/routes — the basket, and per-route fare series."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from apix_api.db import SessionDep  # noqa: TC001
from apix_api.errors import ERROR_RESPONSES
from apix_api.meta import build_meta
from apix_api.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorParam,
    LimitParam,
    Page,
    paginate_in_memory,
    query_signature,
)
from apix_api.schemas import RouteSeriesPoint, RouteSummary
from apix_core.config import load_basket
from apix_core.models import Airport, FareQuoteClean, Route

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
    session: SessionDep,
    basket_version: Annotated[
        str | None, Query(description="Defaults to the basket in force today.")
    ] = None,
    active_on: Annotated[date | None, Query(description="Only routes active on this date.")] = None,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
) -> Page[RouteSummary]:
    """List the basket.

    ``dgca_pax_share`` is null on every route until the DGCA release is loaded into
    ``config/basket.yaml``. That null is the honest answer, not a missing field.
    """
    basket = load_basket()
    version = basket_version or basket.basket_version

    origin = aliased(Airport)
    dest = aliased(Airport)
    stmt = (
        select(Route, origin, dest)
        .join(origin, origin.iata == Route.origin_iata)
        .join(dest, dest.iata == Route.dest_iata)
        .where(Route.basket_version == version)
        .order_by(Route.code)
    )
    if active_on is not None:
        stmt = stmt.where(
            Route.active_from <= active_on,
            (Route.active_to.is_(None)) | (Route.active_to > active_on),
        )
    rows = (await session.execute(stmt)).all()

    items = [
        RouteSummary(
            code=route.code,
            origin_iata=route.origin_iata,
            origin_city=origin_airport.city,
            dest_iata=route.dest_iata,
            dest_city=dest_airport.city,
            dgca_pax_share=(
                float(route.dgca_pax_share) if route.dgca_pax_share is not None else None
            ),
            basket_version=route.basket_version,
            active_from=route.active_from,
            active_to=route.active_to,
            origin_lat=float(origin_airport.lat) if origin_airport.lat is not None else None,
            origin_lon=float(origin_airport.lon) if origin_airport.lon is not None else None,
            dest_lat=float(dest_airport.lat) if dest_airport.lat is not None else None,
            dest_lon=float(dest_airport.lon) if dest_airport.lon is not None else None,
        )
        for route, origin_airport, dest_airport in rows
    ]

    sig = query_signature(basket_version=basket_version, active_on=active_on)
    page_items, page_info = paginate_in_memory(
        items, cursor=cursor, limit=limit, query_sig=sig, position_of=lambda r: {"code": r.code}
    )
    return Page[RouteSummary](
        items=page_items,
        pagination=page_info,
        meta=build_meta(basket_version=version, data_status="PUBLISHED"),
    )


@router.get(
    "/routes/{code}/series",
    summary="Fare series for one route",
    response_model=Page[RouteSeriesPoint],
)
async def get_route_series(
    session: SessionDep,
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
    right-skewed: the mean alone misrepresents what a traveller pays. Grouped by the
    day fares were observed (``query_date``, derived as ``travel_date - advance_days``)
    and, when ``advance_days`` is not filtered, reported at the 14-day lead time
    (the mid-window default the shipped basket documents) rather than blending lead
    times of very different price levels into one misleading average.
    """
    route_id = (
        await session.execute(select(Route.id).where(Route.code == code))
    ).scalar_one_or_none()
    if route_id is None:
        raise HTTPException(status_code=404, detail=f"no route with code {code!r}")

    effective_advance_days = advance_days if advance_days is not None else 14
    query_date_expr = (FareQuoteClean.travel_date - FareQuoteClean.advance_days).label("query_date")

    stmt = (
        select(
            query_date_expr,
            func.avg(FareQuoteClean.total_fare).label("mean_fare"),
            func.percentile_cont(0.5).within_group(FareQuoteClean.total_fare).label("median_fare"),
            func.percentile_cont(0.25).within_group(FareQuoteClean.total_fare).label("p25_fare"),
            func.percentile_cont(0.75).within_group(FareQuoteClean.total_fare).label("p75_fare"),
            func.count(FareQuoteClean.id).label("n_quotes"),
            func.bool_and(FareQuoteClean.is_imputed).label("sold_out"),
        )
        .where(
            FareQuoteClean.route_id == route_id,
            FareQuoteClean.advance_days == effective_advance_days,
            ~FareQuoteClean.is_outlier,
        )
        .group_by(query_date_expr)
        .order_by(query_date_expr)
    )
    if carrier is not None:
        stmt = stmt.where(FareQuoteClean.carrier_iata == carrier)
    if from_ is not None:
        stmt = stmt.where(query_date_expr >= from_)
    if to is not None:
        stmt = stmt.where(query_date_expr <= to)

    rows = (await session.execute(stmt)).all()
    items = [
        RouteSeriesPoint(
            period=period,
            advance_days=effective_advance_days,
            carrier_iata=carrier,
            mean_fare=float(mean_fare),
            median_fare=float(median_fare),
            p25_fare=float(p25_fare),
            p75_fare=float(p75_fare),
            n_quotes=int(n_quotes),
            sold_out=bool(sold_out),
            currency="INR",
        )
        for period, mean_fare, median_fare, p25_fare, p75_fare, n_quotes, sold_out in rows
    ]

    sig = query_signature(code=code, advance_days=advance_days, carrier=carrier, from_=from_, to=to)
    page_items, page_info = paginate_in_memory(
        items,
        cursor=cursor,
        limit=limit,
        query_sig=sig,
        position_of=lambda p: {"period": str(p.period)},
    )
    return Page[RouteSeriesPoint](
        items=page_items, pagination=page_info, meta=build_meta(data_status="PUBLISHED")
    )
