"""/v1/index — the published index series, and its vintages."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, cast

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import func, select

# RoleDep/SessionDep are Annotated[..., Depends(...)] aliases used directly as route
# parameter annotations below; FastAPI resolves them via get_type_hints() at request
# time, so — unlike a plain type-only import — these must stay real, not TYPE_CHECKING.
from apix_api.auth import RoleDep  # noqa: TC001
from apix_api.cache import build_key, cache_get_json, cache_set_json
from apix_api.db import SessionDep  # noqa: TC001
from apix_api.errors import ERROR_RESPONSES
from apix_api.meta import build_meta
from apix_api.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorParam,
    LimitParam,
    Page,
    ResponseMeta,
    paginate_in_memory,
    query_signature,
)
from apix_api.queries import (
    get_series_id,
    get_series_ids_by_prefix,
    imputed_run_periods,
    latest_run_fingerprint,
    latest_values,
    latest_values_multi,
    visible_runs_filter,
)
from apix_api.schemas import IndexPoint, RevisionEntry, RouteContribution, VintageValue
from apix_core.config import load_basket, load_method
from apix_core.models import IndexRun, IndexValue, RevisionLog, Series
from apix_core.settings import get_settings

router = APIRouter(prefix="/v1", tags=["index"], responses=ERROR_RESPONSES)

SeriesParam = Annotated[
    str,
    Query(
        description="Series code. See /v1/metadata/method for the published code list.",
        examples=["APIX.ALL.M"],
        max_length=64,
    ),
]
FreqParam = Annotated[
    str,
    Query(
        pattern="^[DWMQA]$",
        description="SDMX frequency code: D, W, M, Q or A.",
        examples=["M"],
    ),
]


def _meta() -> ResponseMeta:
    basket = load_basket()
    method = load_method()
    return build_meta(method_version=method.method_version, basket_version=basket.basket_version)


@router.get(
    "/index",
    summary="Published index series",
    response_model=Page[IndexPoint],
    response_model_exclude_none=False,
)
async def get_index(
    request: Request,
    response: Response,
    session: SessionDep,
    role: RoleDep,
    series: SeriesParam = "APIX.ALL.M",
    freq: FreqParam = "M",
    from_: Annotated[
        date | None, Query(alias="from", description="Inclusive start period.")
    ] = None,
    to: Annotated[date | None, Query(description="Inclusive end period.")] = None,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
) -> Page[IndexPoint]:
    """Return the index for a series over a period range.

    The value, the number of quotes behind it and the basket coverage travel together:
    a consumer is never handed a number without the evidence base for it. For each
    period, this is the current best estimate — the most recent vintage of that period
    a caller with this role can see.

    A series with no published values yet (the headline ``APIX.ALL.M``, until DGCA
    passenger-share weights are loaded — see docs/data-sources.md) answers with an
    empty page, not a 404: an unpublished series is a recorded gap, not an error, and
    a series *code* is not validated against a fixed enum at this layer.

    Cached (``apix_api.cache``) keyed on the resolved series' latest visible run id, so
    a new index run invalidates naturally — a stale cache entry can only ever be served
    up to the moment a newer run exists, never past it.
    """
    series_id = await get_series_id(session, series)
    run_fingerprint = await latest_run_fingerprint(
        session, [series_id] if series_id is not None else [], role=role
    )
    cache_key = build_key(
        "index", series=series, freq=freq, from_=from_, to=to, role=role.value, run=run_fingerprint
    )
    redis = request.app.state.cache_redis
    cached_raw = await cache_get_json(redis, cache_key)
    cached = cast("dict[str, Any] | None", cached_raw)

    if cached is not None:
        items = [IndexPoint.model_validate(raw) for raw in cached["items"]]
        any_provisional = bool(cached["any_provisional"])
    else:
        rows = (
            []
            if series_id is None
            else await latest_values(session, series_id, role=role, from_period=from_, to_period=to)
        )
        imputed = set() if series_id is None else await imputed_run_periods(session, series_id)

        items = []
        any_provisional = False
        for row in rows:
            released = row["released_at"] is not None
            any_provisional = any_provisional or not released
            coverage_pct = row["coverage_pct"]
            items.append(
                IndexPoint(
                    series=series,
                    period=row["period"],
                    value=float(row["value"]),
                    n_quotes=int(row["n_quotes"]),
                    coverage_pct=float(coverage_pct) if coverage_pct is not None else None,
                    is_imputed=(row["index_run_id"], row["period"]) in imputed,
                    status=(
                        "PUBLISHED"
                        if released and row["revision_count"] == 0
                        else "REVISED"
                        if released
                        else "PROVISIONAL"
                    ),
                )
            )
        await cache_set_json(
            redis,
            cache_key,
            {
                "items": [item.model_dump(mode="json") for item in items],
                "any_provisional": any_provisional,
            },
            ttl_s=get_settings().api_cache_ttl_s,
        )

    sig = query_signature(series=series, freq=freq, from_=from_, to=to)
    page_items, page_info = paginate_in_memory(
        items,
        cursor=cursor,
        limit=limit,
        query_sig=sig,
        position_of=lambda p: {"period": str(p.period)},
    )
    response.headers["X-APIx-Data-Status"] = "PROVISIONAL" if any_provisional else "PUBLISHED"
    return Page[IndexPoint](items=page_items, pagination=page_info, meta=_meta())


@router.get(
    "/index/vintage",
    summary="A period's value as it stood on a given date",
    response_model=VintageValue,
)
async def get_index_vintage(
    response: Response,
    session: SessionDep,
    role: RoleDep,
    series: SeriesParam = "APIX.ALL.M",
    period: Annotated[date, Query(description="The period being asked about.")] = date(2026, 8, 1),
    as_of: Annotated[date, Query(description="Report the value as it stood on this date.")] = date(
        2026, 9, 1
    ),
) -> VintageValue:
    """Answer "what did we say this period was, on that date".

    Resolves against ``index_run.vintage_date``, not merely the latest run: among every
    run whose ``vintage_date <= as_of`` and that published a value for ``period``, the
    one with the latest ``vintage_date`` (ties broken by ``computed_at``) is what a
    consumer asking on that date would have been told. Revisions are visible rather
    than silent: ``index_value`` rows are never overwritten, so every vintage remains
    queryable and every change appears in ``revision_log``.
    """
    series_id = await get_series_id(session, series)
    if series_id is None:
        raise HTTPException(status_code=404, detail=f"no series is published with code {series!r}")

    stmt = (
        select(IndexValue.value, IndexValue.index_run_id, IndexRun.released_at)
        .join(IndexRun, IndexRun.id == IndexValue.index_run_id)
        .where(
            IndexValue.series_id == series_id,
            IndexValue.period == period,
            IndexRun.vintage_date <= as_of,
            visible_runs_filter(role),
        )
        .order_by(IndexRun.vintage_date.desc(), IndexRun.computed_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"no value for series={series!r} period={period} as of {as_of}",
        )
    value, index_run_id, released_at = row

    revision = (
        await session.execute(
            select(RevisionLog.old_value, RevisionLog.reason)
            .where(
                RevisionLog.series_id == series_id,
                RevisionLog.period == period,
                RevisionLog.new_value == value,
            )
            .order_by(RevisionLog.revised_at.desc())
            .limit(1)
        )
    ).first()

    response.headers["X-APIx-Data-Status"] = (
        "PUBLISHED" if released_at is not None else "PROVISIONAL"
    )
    return VintageValue(
        series=series,
        period=period,
        as_of=as_of,
        value=float(value),
        index_run_id=str(index_run_id),
        revised_from=float(revision[0]) if revision and revision[0] is not None else None,
        revision_reason=revision[1] if revision else None,
    )


@router.get(
    "/index/contributors",
    summary="Route indices behind one headline value",
    response_model=Page[RouteContribution],
)
async def get_index_contributors(
    session: SessionDep,
    role: RoleDep,
    series: SeriesParam = "APIX.ALL.M",
    period: Annotated[
        date, Query(description="The period whose value is being decomposed by route.")
    ] = date(2026, 8, 1),
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
) -> Page[RouteContribution]:
    """Audit drill-down, level 2: headline value -> the route indices it aggregates.

    ``weight`` and ``contribution_pct_points`` are null until DGCA passenger shares are
    loaded into ``config/basket.yaml`` — the aggregation is unweighted today and the
    response says so rather than serving an estimated weight.
    """
    route_series = await get_series_ids_by_prefix(session, "APIX.ROUTE.%.M")
    rows = await latest_values_multi(
        session, list(route_series), role=role, from_period=period, to_period=period
    )
    items = [
        RouteContribution(
            route_code=route_series[row["series_id"]]["dimensions"].get("route_code", ""),
            series=route_series[row["series_id"]]["code"],
            period=period,
            index_value=float(row["value"]),
            weight=None,
            contribution_pct_points=None,
            n_quotes=int(row["n_quotes"]),
        )
        for row in rows
    ]
    items.sort(key=lambda item: item.route_code)

    sig = query_signature(series=series, period=period)
    page_items, page_info = paginate_in_memory(
        items,
        cursor=cursor,
        limit=limit,
        query_sig=sig,
        position_of=lambda r: {"route_code": r.route_code},
    )
    return Page[RouteContribution](items=page_items, pagination=page_info, meta=_meta())


@router.get(
    "/index/revisions",
    summary="The revision log",
    response_model=Page[RevisionEntry],
)
async def get_index_revisions(
    session: SessionDep,
    series: Annotated[
        str | None, Query(max_length=64, description="Restrict to one series. Null = all.")
    ] = None,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
) -> Page[RevisionEntry]:
    """Every change to a published value, with when and why.

    First publications appear with ``old_value = null`` so the log is a complete history
    of what was said, not only of what changed. ``index_run_id`` is not a stored column
    on ``revision_log`` (it records the change, not which run made it), so it is
    resolved back through ``index_value`` — matched on (series, period, value) — in the
    same query rather than one lookup per row: a window function keeps exactly one
    candidate run per revision even if two runs coincidentally spliced to the same
    value for the same period.
    """
    run_rank = (
        func.row_number()
        .over(partition_by=RevisionLog.id, order_by=IndexRun.computed_at.desc())
        .label("run_rank")
    )
    stmt = (
        select(
            RevisionLog.id,
            RevisionLog.revised_at,
            Series.code,
            RevisionLog.period,
            RevisionLog.old_value,
            RevisionLog.new_value,
            RevisionLog.reason,
            IndexRun.id.label("index_run_id"),
            run_rank,
        )
        .select_from(RevisionLog)
        .join(Series, Series.id == RevisionLog.series_id)
        .outerjoin(
            IndexValue,
            (IndexValue.series_id == RevisionLog.series_id)
            & (IndexValue.period == RevisionLog.period)
            & (IndexValue.value == RevisionLog.new_value),
        )
        .outerjoin(IndexRun, IndexRun.id == IndexValue.index_run_id)
    )
    if series is not None:
        stmt = stmt.where(Series.code == series)
    ranked = stmt.subquery()
    final = (
        select(
            ranked.c.revised_at,
            ranked.c.code,
            ranked.c.period,
            ranked.c.old_value,
            ranked.c.new_value,
            ranked.c.reason,
            ranked.c.index_run_id,
        )
        .where(ranked.c.run_rank == 1)
        .order_by(ranked.c.revised_at.desc())
    )
    rows = (await session.execute(final)).all()

    items = [
        RevisionEntry(
            revised_at=revised_at.isoformat(),
            series=series_code,
            period=period,
            old_value=float(old_value) if old_value is not None else None,
            new_value=float(new_value),
            reason=reason,
            index_run_id=str(index_run_id) if index_run_id else "",
        )
        for revised_at, series_code, period, old_value, new_value, reason, index_run_id in rows
    ]

    sig = query_signature(series=series)
    page_items, page_info = paginate_in_memory(
        items,
        cursor=cursor,
        limit=limit,
        query_sig=sig,
        position_of=lambda r: {"revised_at": r.revised_at},
    )
    return Page[RevisionEntry](items=page_items, pagination=page_info, meta=_meta())
