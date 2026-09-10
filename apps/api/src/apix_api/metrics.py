"""Prometheus metrics.

``apix_http_request_duration_seconds`` is recorded by middleware on every request.
The gauges are refreshed just-in-time inside the ``/metrics`` handler itself — a real
async read against the database right before ``generate_latest()`` — rather than by a
background scheduler, which would be one more process to keep alive for three gauges.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING

from prometheus_client import Gauge, Histogram
from sqlalchemy import Integer, cast, func, select

from apix_core.models import CollectionRun, IndexRun, IndexValue, RunStatus, Series, Source

if TYPE_CHECKING:
    from fastapi import FastAPI, Request, Response
    from sqlalchemy.ext.asyncio import AsyncSession

REQUEST_DURATION = Histogram(
    "apix_http_request_duration_seconds",
    "Time spent handling a request.",
    labelnames=("method", "path", "status"),
)

INDEX_STALENESS = Gauge(
    "apix_index_staleness_seconds",
    "Seconds since the most recently released index run was computed.",
)

SERIES_COVERAGE_PCT = Gauge(
    "apix_coverage_pct",
    "Coverage percentage of the latest published value for one series.",
    labelnames=("series",),
)

COLLECTION_SUCCESS_RATE = Gauge(
    "apix_collection_success_rate",
    "Share of recorded collection runs for a source that succeeded.",
    labelnames=("source",),
)


def install_metrics_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def _record_latency(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = route.path if route is not None else request.url.path
        REQUEST_DURATION.labels(
            method=request.method, path=path, status=str(response.status_code)
        ).observe(perf_counter() - start)
        return response


async def refresh_gauges(session: AsyncSession) -> None:
    """Set every gauge from the database. Called once per ``/metrics`` scrape."""
    latest_release = (
        await session.execute(select(func.max(IndexRun.released_at)))
    ).scalar_one_or_none()
    if latest_release is not None:
        INDEX_STALENESS.set((datetime.now(tz=UTC) - latest_release).total_seconds())

    latest_run_id = (
        await session.execute(
            select(IndexRun.id)
            .where(IndexRun.released_at.isnot(None))
            .order_by(IndexRun.released_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_run_id is not None:
        coverage_rows = await session.execute(
            select(Series.code, IndexValue.coverage_pct)
            .join(Series, Series.id == IndexValue.series_id)
            .where(IndexValue.index_run_id == latest_run_id, IndexValue.coverage_pct.isnot(None))
        )
        for series_code, coverage_pct in coverage_rows.all():
            SERIES_COVERAGE_PCT.labels(series=series_code).set(float(coverage_pct))

    success_rows = await session.execute(
        select(
            Source.code,
            func.count(CollectionRun.id),
            func.sum(cast(CollectionRun.status == RunStatus.SUCCEEDED, Integer)),
        )
        .join(CollectionRun, CollectionRun.source_id == Source.id)
        .group_by(Source.code)
    )
    for source_code, total, succeeded in success_rows.all():
        COLLECTION_SUCCESS_RATE.labels(source=source_code).set(
            (int(succeeded or 0) / total) if total else 0.0
        )


__all__ = [
    "COLLECTION_SUCCESS_RATE",
    "INDEX_STALENESS",
    "REQUEST_DURATION",
    "SERIES_COVERAGE_PCT",
    "install_metrics_middleware",
    "refresh_gauges",
]
