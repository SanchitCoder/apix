"""/v1/index — the published index series, and its vintages."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from apix_api.errors import ERROR_RESPONSES
from apix_api.examples import (
    EXAMPLE_INDEX_RUN_ID,
    EXAMPLE_PERIODS,
    EXAMPLE_SERIES_CODE,
    EXAMPLE_VALUES,
    example_offset,
    response_meta,
)
from apix_api.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorParam,
    LimitParam,
    Page,
    PageInfo,
    encode_cursor,
    query_signature,
)
from apix_api.schemas import IndexPoint, RevisionEntry, RouteContribution, VintageValue

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


@router.get(
    "/index",
    summary="Published index series",
    response_model=Page[IndexPoint],
    response_model_exclude_none=False,
)
async def get_index(
    series: SeriesParam = EXAMPLE_SERIES_CODE,
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
    a consumer is never handed a number without the evidence base for it.

    In this phase every series answers with the example values, offset per series code
    so that two series drawn on one chart are visibly two lines. The headline series is
    served unshifted, so the documented examples stay stable.
    """
    shift = 0.0 if series == EXAMPLE_SERIES_CODE else example_offset("index", series)
    items = [
        IndexPoint(
            series=series,
            period=period,
            value=round(value + shift, 1),
            n_quotes=12_500,
            coverage_pct=96.0,
            is_imputed=False,
            status="EXAMPLE_ONLY",
        )
        for period, value in zip(EXAMPLE_PERIODS, EXAMPLE_VALUES, strict=True)
    ]
    sig = query_signature(series=series, freq=freq, from_=from_, to=to)
    return Page[IndexPoint](
        items=items,
        pagination=PageInfo(
            limit=limit,
            returned=len(items),
            has_more=False,
            next_cursor=encode_cursor({"period": str(items[-1].period)}, sig),
        ),
        meta=response_meta(method_version="2026.1", basket_version="2026.1"),
    )


@router.get(
    "/index/vintage",
    summary="A period's value as it stood on a given date",
    response_model=VintageValue,
)
async def get_index_vintage(
    series: SeriesParam = EXAMPLE_SERIES_CODE,
    period: Annotated[date, Query(description="The period being asked about.")] = EXAMPLE_PERIODS[
        -1
    ],
    as_of: Annotated[date, Query(description="Report the value as it stood on this date.")] = date(
        2026, 9, 1
    ),
) -> VintageValue:
    """Answer "what did we say this period was, on that date".

    Revisions are visible rather than silent: ``index_value`` rows are never overwritten,
    so every vintage remains queryable and every change appears in ``revision_log``.
    """
    return VintageValue(
        series=series,
        period=period,
        as_of=as_of,
        value=EXAMPLE_VALUES[-1],
        index_run_id=EXAMPLE_INDEX_RUN_ID,
        revised_from=None,
        revision_reason=None,
    )


@router.get(
    "/index/contributors",
    summary="Route indices behind one headline value",
    response_model=Page[RouteContribution],
)
async def get_index_contributors(
    series: SeriesParam = EXAMPLE_SERIES_CODE,
    period: Annotated[
        date, Query(description="The period whose value is being decomposed by route.")
    ] = EXAMPLE_PERIODS[-1],
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
) -> Page[RouteContribution]:
    """Audit drill-down, level 2: headline value -> the route indices it aggregates.

    ``weight`` and ``contribution_pct_points`` are null until Phase 2 loads DGCA
    passenger shares — the aggregation is unweighted today and the response says so
    rather than serving an estimated weight.
    """
    example_routes = ("DEL-BOM", "BOM-DEL", "DEL-BLR", "BLR-DEL")
    items = [
        RouteContribution(
            route_code=code,
            series=f"APIX.ROUTE.{code}.M",
            period=period,
            index_value=round(EXAMPLE_VALUES[-1] + example_offset("contributor", code), 1),
            weight=None,
            contribution_pct_points=None,
            n_quotes=250,
        )
        for code in example_routes
    ]
    sig = query_signature(series=series, period=period)
    return Page[RouteContribution](
        items=items,
        pagination=PageInfo(
            limit=limit,
            returned=len(items),
            has_more=False,
            next_cursor=encode_cursor({"route_code": items[-1].route_code}, sig),
        ),
        meta=response_meta(method_version="2026.1", basket_version="2026.1"),
    )


@router.get(
    "/index/revisions",
    summary="The revision log",
    response_model=Page[RevisionEntry],
)
async def get_index_revisions(
    series: Annotated[
        str | None, Query(max_length=64, description="Restrict to one series. Null = all.")
    ] = None,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
) -> Page[RevisionEntry]:
    """Every change to a published value, with when and why.

    First publications appear with ``old_value = null`` so the log is a complete history
    of what was said, not only of what changed.
    """
    entries = [
        RevisionEntry(
            revised_at="2026-08-05T09:00:00+00:00",
            series=series or EXAMPLE_SERIES_CODE,
            period=EXAMPLE_PERIODS[-2],
            old_value=None,
            new_value=EXAMPLE_VALUES[-2],
            reason="First publication of the period.",
            index_run_id=EXAMPLE_INDEX_RUN_ID,
        ),
        RevisionEntry(
            revised_at="2026-09-03T09:00:00+00:00",
            series=series or EXAMPLE_SERIES_CODE,
            period=EXAMPLE_PERIODS[-2],
            old_value=EXAMPLE_VALUES[-2],
            new_value=round(EXAMPLE_VALUES[-2] + 0.5, 1),
            reason="Late-arriving source data for two routes; see index_run for the snapshot.",
            index_run_id="00000000-0000-4000-8000-000000000006",
        ),
    ]
    sig = query_signature(series=series)
    return Page[RevisionEntry](
        items=entries,
        pagination=PageInfo(
            limit=limit,
            returned=len(entries),
            has_more=False,
            next_cursor=encode_cursor({"revised_at": entries[-1].revised_at}, sig),
        ),
        meta=response_meta(method_version="2026.1", basket_version="2026.1"),
    )
