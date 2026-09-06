"""/v1/leadtime, /v1/heatmap, /v1/decomposition, /v1/nowcast, /v1/coverage.

The analytical views the dashboard is built from.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Path, Query

from apix_api.errors import ERROR_RESPONSES
from apix_api.examples import EXAMPLE_PERIODS, EXAMPLE_SERIES_CODE, example_offset, response_meta
from apix_api.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorParam,
    LimitParam,
    Page,
    PageInfo,
    encode_cursor,
    query_signature,
)
from apix_api.schemas import (
    CoverageResponse,
    DecompositionComponent,
    DecompositionResponse,
    HeatmapCell,
    LeadTimeBucket,
    LeadTimeResponse,
    NowcastPoint,
    SourceCoverage,
)

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
    route, which is the comparison a traveller actually cares about. The quartiles carry
    the dispersion the chart draws as a band. A ``carrier`` filter shifts the example
    curve deterministically so a split chart draws distinct, stable lines.
    """
    windows = [
        ("AP00_03", 0, 3, 9000.0, 8800.0, 180.0),
        ("AP04_07", 4, 7, 7500.0, 7300.0, 150.0),
        ("AP08_14", 8, 14, 6000.0, 5900.0, 120.0),
        ("AP15_21", 15, 21, 5500.0, 5400.0, 110.0),
        ("AP22_30", 22, 30, 5200.0, 5100.0, 104.0),
        ("AP31_60", 31, 60, 5000.0, 4900.0, 100.0),
        ("AP61_90", 61, 90, 5100.0, 5000.0, 102.0),
    ]
    shift = 0.0 if carrier is None else example_offset("leadtime", carrier, scale=200)
    return LeadTimeResponse(
        route_code=code,
        carrier_iata=carrier,
        currency="INR",
        buckets=[
            LeadTimeBucket(
                window_code=wc,
                min_days=lo,
                max_days=hi,
                mean_fare=mean + shift,
                median_fare=median + shift,
                p25_fare=round((mean + shift) * 0.82, 0),
                p75_fare=round((mean + shift) * 1.22, 0),
                n_quotes=250,
                index_vs_cheapest=rel,
            )
            for wc, lo, hi, mean, median, rel in windows
        ],
        meta=response_meta(method_version="2026.1", basket_version="2026.1"),
    )


@router.get("/heatmap", summary="Route-by-period index heatmap", response_model=Page[HeatmapCell])
async def get_heatmap(
    from_: Annotated[date | None, Query(alias="from", description="Inclusive start.")] = None,
    to: Annotated[date | None, Query(description="Inclusive end.")] = None,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
) -> Page[HeatmapCell]:
    """The route x period grid the dashboard renders as a heatmap.

    Paginated like every other list endpoint: 50 routes over several years is a large
    grid, and the client should not have to guess how much it is about to receive.
    """
    # Offset per (route, period) so the heatmap's diverging scale has real variation to
    # show. Deterministic: the same grid is served on every request.
    items = [
        HeatmapCell(
            route_code=code,
            period=period,
            value=round(value + example_offset("heatmap", code, str(period)), 1),
            n_quotes=250,
        )
        for code in ("DEL-BOM", "BOM-DEL", "DEL-BLR", "BLR-DEL")
        for period, value in zip(EXAMPLE_PERIODS, (100.0, 101.5, 103.0, 102.5, 105.5), strict=True)
    ]
    sig = query_signature(from_=from_, to=to)
    return Page[HeatmapCell](
        items=items,
        pagination=PageInfo(
            limit=limit,
            returned=len(items),
            has_more=False,
            next_cursor=encode_cursor(
                {"route_code": items[-1].route_code, "period": str(items[-1].period)}, sig
            ),
        ),
        meta=response_meta(method_version="2026.1", basket_version="2026.1"),
    )


@router.get(
    "/decomposition",
    summary="What moved the index in a period",
    response_model=DecompositionResponse,
)
async def get_decomposition(
    period: Annotated[date, Query(description="Period to decompose.")] = EXAMPLE_PERIODS[-1],
    series: Annotated[str, Query(max_length=64)] = EXAMPLE_SERIES_CODE,
) -> DecompositionResponse:
    """Split a period-on-period movement into additive contributions.

    The residual is reported as its own line rather than distributed across the named
    components. A decomposition that always adds to exactly 100% is hiding something.
    """
    components = [
        ("base_fare", 2.1, 0.70),
        ("taxes", 0.3, 0.10),
        ("udf", 0.0, 0.00),
        ("convenience_fee", 0.1, 0.03),
        ("mix_route", 0.2, 0.07),
        ("mix_carrier", 0.1, 0.03),
        ("mix_advance_window", 0.1, 0.03),
        ("quality_adjustment", -0.1, -0.03),
    ]
    return DecompositionResponse(
        period=period,
        series=series,
        total_movement_pct=3.0,
        components=[
            DecompositionComponent(
                component=name, contribution_pct_points=pts, share_of_movement=share
            )
            for name, pts, share in components
        ],
        residual_pct_points=0.2,
        meta=response_meta(method_version="2026.1", basket_version="2026.1"),
    )


@router.get(
    "/nowcast",
    summary="Model estimate for the period that has not closed",
    response_model=Page[NowcastPoint],
)
async def get_nowcast(
    target_series: Annotated[str, Query(max_length=64)] = EXAMPLE_SERIES_CODE,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_PAGE_SIZE,
) -> Page[NowcastPoint]:
    """Return the current nowcast.

    Served from ``nowcast_value``, never from ``index_value``: a modelled estimate of an
    open period must not be mistakable for a published index number. Every point carries
    an explicit caveat saying so.
    """
    items = [
        NowcastPoint(
            target_series=target_series,
            target_period=date(2026, 9, 1),
            point_estimate=106.0,
            ci_low=104.5,
            ci_high=107.5,
            ci_level=0.80,
            model_version="0.0.0-not-yet-fitted",
            produced_at=datetime.now(tz=UTC).isoformat(),
        )
    ]
    sig = query_signature(target_series=target_series)
    return Page[NowcastPoint](
        items=items,
        pagination=PageInfo(
            limit=limit,
            returned=len(items),
            has_more=False,
            next_cursor=encode_cursor({"target_period": "2026-09-01"}, sig),
        ),
        meta=response_meta(method_version="2026.1", with_run=False),
    )


@router.get(
    "/coverage",
    summary="What was collected on a date, and what was not",
    response_model=CoverageResponse,
)
async def get_coverage(
    date_: Annotated[date, Query(alias="date", description="Collection date.")] = date(2026, 9, 1),
) -> CoverageResponse:
    """Report collection coverage, including every gap.

    ``routes_missing`` and a per-source status with a reason are the operational form of
    "nothing fails silently". A blocked source appears here with why it was blocked.
    """
    return CoverageResponse(
        date=date_,
        routes_expected=50,
        routes_covered=48,
        coverage_pct=96.0,
        routes_missing=["DEL-SXR", "SXR-DEL"],
        sources=[
            SourceCoverage(
                source_code="fixture_replay",
                status="OK",
                quotes_collected=12_500,
                blocked_count=0,
                reason=None,
            ),
            SourceCoverage(
                source_code="ota_makemytrip",
                status="DISABLED",
                quotes_collected=0,
                blocked_count=0,
                reason="tos_verdict is NOT_REVIEWED; the source has never been enabled.",
            ),
        ],
        meta=response_meta(basket_version="2026.1", with_run=False),
    )
