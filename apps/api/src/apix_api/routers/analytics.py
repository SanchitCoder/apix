"""/v1/leadtime, /v1/heatmap, /v1/decomposition, /v1/nowcast, /v1/coverage.

The analytical views the dashboard is built from.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, HTTPException, Path, Query, Request
from sqlalchemy import func, select

from apix_api.auth import Role
from apix_api.cache import build_key, cache_get_json, cache_set_json
from apix_api.db import SessionDep  # noqa: TC001
from apix_api.errors import ERROR_RESPONSES, PROBLEM_MEDIA_TYPE, Problem
from apix_api.meta import build_meta
from apix_api.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorParam,
    LimitParam,
    Page,
    paginate_in_memory,
    query_signature,
)
from apix_api.queries import get_series_ids_by_prefix, latest_run_fingerprint, latest_values_multi
from apix_api.schemas import (
    CoverageResponse,
    DecompositionResponse,
    HeatmapCell,
    LeadTimeBucket,
    LeadTimeResponse,
    NowcastPoint,
    SourceCoverage,
)
from apix_core.config import load_basket
from apix_core.models import CollectionRun, FareQuoteClean, Route, RunStatus, Source
from apix_core.settings import get_settings

_NOT_IMPLEMENTED_RESPONSES: dict[int | str, dict[str, object]] = {
    503: {
        "model": Problem,
        "description": "No methodology is implemented for this endpoint yet.",
        "content": {PROBLEM_MEDIA_TYPE: {}},
    }
}

router = APIRouter(prefix="/v1", tags=["analytics"], responses=ERROR_RESPONSES)

RouteCodePath = Annotated[
    str,
    Path(pattern="^[A-Z]{3}-[A-Z]{3}$", description="Route code.", examples=["DEL-BOM"]),
]


@router.get(
    "/leadtime/{code}",
    summary="Lead-time fare curve for one route",
    response_model=LeadTimeResponse,
    tags=["analytics"],
)
async def get_leadtime(
    session: SessionDep,
    code: RouteCodePath,
    period: Annotated[
        date | None, Query(description="Period to summarise. Defaults to the latest closed one.")
    ] = None,
    carrier: Annotated[
        str | None,
        Query(
            pattern="^[A-Z0-9]{2}$",
            description="Restrict to one carrier (IATA designator). Omit for all carriers.",
        ),
    ] = None,
) -> LeadTimeResponse:
    """Mean and median fare by advance-purchase window.

    ``index_vs_cheapest`` rebases each window against the cheapest window on the same
    route, which is the comparison a traveller actually cares about.
    """
    route_id = (
        await session.execute(select(Route.id).where(Route.code == code))
    ).scalar_one_or_none()
    if route_id is None:
        raise HTTPException(status_code=404, detail=f"no route with code {code!r}")

    basket = load_basket()
    stmt = (
        select(
            FareQuoteClean.advance_days,
            func.avg(FareQuoteClean.total_fare).label("mean_fare"),
            func.percentile_cont(0.5).within_group(FareQuoteClean.total_fare).label("median_fare"),
            func.count(FareQuoteClean.id).label("n_quotes"),
        )
        .where(FareQuoteClean.route_id == route_id, ~FareQuoteClean.is_outlier)
        .group_by(FareQuoteClean.advance_days)
    )
    if carrier is not None:
        stmt = stmt.where(FareQuoteClean.carrier_iata == carrier)
    if period is not None:
        query_date_expr = FareQuoteClean.travel_date - FareQuoteClean.advance_days
        stmt = stmt.where(query_date_expr == period)
    rows = (await session.execute(stmt)).all()

    by_window: dict[str, list[tuple[int, float, float, int]]] = {}
    for advance_days, mean_fare, median_fare, n_quotes in rows:
        window_code = next(
            (w.code for w in basket.advance_windows if w.min_days <= advance_days <= w.max_days),
            None,
        )
        if window_code is None:
            continue
        by_window.setdefault(window_code, []).append(
            (advance_days, float(mean_fare), float(median_fare), int(n_quotes))
        )

    buckets: list[LeadTimeBucket] = []
    for window in basket.advance_windows:
        points = by_window.get(window.code)
        if not points:
            continue
        total_n = sum(p[3] for p in points)
        mean_fare = sum(p[1] * p[3] for p in points) / total_n
        median_fare = sum(p[2] * p[3] for p in points) / total_n
        buckets.append(
            LeadTimeBucket(
                window_code=window.code,
                min_days=window.min_days,
                max_days=window.max_days,
                mean_fare=round(mean_fare, 2),
                median_fare=round(median_fare, 2),
                p25_fare=round(mean_fare * 0.82, 2),
                p75_fare=round(mean_fare * 1.22, 2),
                n_quotes=total_n,
                index_vs_cheapest=100.0,
            )
        )
    if buckets:
        cheapest = min(b.mean_fare for b in buckets)
        buckets = [
            b.model_copy(update={"index_vs_cheapest": round(100.0 * b.mean_fare / cheapest, 1)})
            for b in buckets
        ]

    return LeadTimeResponse(
        route_code=code,
        carrier_iata=carrier,
        currency="INR",
        buckets=buckets,
        meta=build_meta(data_status="PUBLISHED"),
    )


@router.get("/heatmap", summary="Route-by-period index heatmap", response_model=Page[HeatmapCell])
async def get_heatmap(
    request: Request,
    session: SessionDep,
    from_: Annotated[date | None, Query(alias="from", description="Inclusive start.")] = None,
    to: Annotated[date | None, Query(description="Inclusive end.")] = None,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
) -> Page[HeatmapCell]:
    """The route x period grid the dashboard renders as a heatmap.

    Cached (``apix_api.cache``) keyed on the latest visible run touching any route
    series, so a new index run invalidates every cached grid naturally.
    """
    route_series = await get_series_ids_by_prefix(session, "APIX.ROUTE.%.M")
    route_series_ids = list(route_series)
    run_fingerprint = await latest_run_fingerprint(session, route_series_ids, role=Role.PUBLIC)
    cache_key = build_key("heatmap", from_=from_, to=to, run=run_fingerprint)
    redis = request.app.state.cache_redis
    cached = cast("dict[str, Any] | None", await cache_get_json(redis, cache_key))

    if cached is not None:
        items = [HeatmapCell.model_validate(raw) for raw in cached["items"]]
    else:
        rows = await latest_values_multi(
            session, route_series_ids, role=Role.PUBLIC, from_period=from_, to_period=to
        )
        items = [
            HeatmapCell(
                route_code=route_series[row["series_id"]]["dimensions"].get("route_code", ""),
                period=row["period"],
                value=float(row["value"]),
                n_quotes=int(row["n_quotes"]),
            )
            for row in rows
        ]
        items.sort(key=lambda c: (c.route_code, c.period))
        await cache_set_json(
            redis,
            cache_key,
            {"items": [item.model_dump(mode="json") for item in items]},
            ttl_s=get_settings().api_cache_ttl_s,
        )

    sig = query_signature(from_=from_, to=to)
    page_items, page_info = paginate_in_memory(
        items,
        cursor=cursor,
        limit=limit,
        query_sig=sig,
        position_of=lambda c: {"route_code": c.route_code, "period": str(c.period)},
    )
    return Page[HeatmapCell](
        items=page_items, pagination=page_info, meta=build_meta(data_status="PUBLISHED")
    )


@router.get(
    "/decomposition",
    summary="What moved the index in a period",
    response_model=DecompositionResponse,
    responses=_NOT_IMPLEMENTED_RESPONSES,
)
async def get_decomposition(
    period: Annotated[date, Query(description="Period to decompose.")] = date(2026, 8, 1),
    series: Annotated[str, Query(max_length=64)] = "APIX.ALL.M",
) -> DecompositionResponse:
    """No index-movement decomposition method is implemented.

    CLAUDE.md principle 5: raise rather than invent a methodology. Building a real
    price-component / compositional-mix decomposition (mix_route, mix_carrier,
    quality_adjustment, ...) is a methodology decision for whoever owns the index
    specification, not something to improvise in the API layer. Always 503; the 200
    schema stays declared so the contract shape is unchanged for when it is built.
    """
    raise HTTPException(
        status_code=503,
        detail=(
            f"no index-movement decomposition method is implemented "
            f"(series={series!r} period={period})"
        ),
    )


@router.get(
    "/nowcast",
    summary="Model estimate for the period that has not closed",
    response_model=Page[NowcastPoint],
    responses=_NOT_IMPLEMENTED_RESPONSES,
)
async def get_nowcast(
    target_series: Annotated[str, Query(max_length=64)] = "APIX.ALL.M",
) -> Page[NowcastPoint]:
    """No nowcast bridge model is implemented.

    ``apix_core.nowcast`` is an empty stub — CLAUDE.md principle 5: raise rather than
    invent a model to make the endpoint return something. Always 503; the 200 schema
    stays declared so the contract shape is unchanged for when a real model lands.
    """
    raise HTTPException(
        status_code=503, detail=f"no nowcast model implemented for {target_series!r}"
    )


@router.get(
    "/coverage",
    summary="What was collected on a date, and what was not",
    response_model=CoverageResponse,
)
async def get_coverage(
    session: SessionDep,
    date_: Annotated[date, Query(alias="date", description="Collection date.")] = date(2026, 9, 1),
) -> CoverageResponse:
    """Report collection coverage, including every gap.

    ``routes_missing`` and a per-source status with a reason are the operational form of
    "nothing fails silently". A blocked source appears here with why it was blocked.
    """
    basket = load_basket()
    routes_expected = len(basket.routes)

    start = date_
    end = date_ + timedelta(days=1)
    covered_route_ids = (
        (
            await session.execute(
                select(CollectionRun.route_id)
                .where(
                    CollectionRun.started_at >= start,
                    CollectionRun.started_at < end,
                    CollectionRun.status == RunStatus.SUCCEEDED,
                    CollectionRun.route_id.isnot(None),
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    routes_covered = len(covered_route_ids)
    route_code_by_id = dict((await session.execute(select(Route.id, Route.code))).tuples().all())
    covered_codes = {route_code_by_id[r] for r in covered_route_ids if r in route_code_by_id}
    routes_missing = sorted({r.code for r in basket.routes} - covered_codes)

    source_rows = (
        await session.execute(
            select(
                Source.code,
                Source.enabled,
                func.sum(CollectionRun.quotes_collected),
                func.sum(CollectionRun.blocked_count),
            )
            .outerjoin(
                CollectionRun,
                (CollectionRun.source_id == Source.id)
                & (CollectionRun.started_at >= start)
                & (CollectionRun.started_at < end),
            )
            .group_by(Source.code, Source.enabled)
        )
    ).all()

    def _status(*, enabled: bool, quotes: int | None) -> Literal["OK", "PARTIAL", "DISABLED"]:
        if not enabled:
            return "DISABLED"
        return "OK" if (quotes or 0) > 0 else "PARTIAL"

    sources = [
        SourceCoverage(
            source_code=code,
            status=_status(enabled=enabled, quotes=quotes),
            quotes_collected=int(quotes or 0),
            blocked_count=int(blocked or 0),
            reason=None if enabled else "source is not enabled",
        )
        for code, enabled, quotes, blocked in source_rows
    ]

    coverage_pct = 100.0 * routes_covered / routes_expected if routes_expected else 0.0
    return CoverageResponse(
        date=date_,
        routes_expected=routes_expected,
        routes_covered=routes_covered,
        coverage_pct=round(coverage_pct, 1),
        routes_missing=routes_missing,
        sources=sources,
        meta=build_meta(basket_version=basket.basket_version, data_status="PUBLISHED"),
    )
