"""Shared async query helpers used by more than one router.

Kept here rather than duplicated per-router so the "latest published value per period"
and "is this run visible to this caller" rules are defined exactly once, and so that a
request touching many series (contributors, heatmap) does it in one query instead of
one per series — the N+1 pattern the task explicitly calls out to avoid.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, TypedDict

from sqlalchemy import ColumnElement, and_, func, select, true

from apix_core.models import (
    FareQuoteClean,
    IndexRun,
    IndexValue,
    IndexValueQuote,
    RevisionLog,
    Series,
)
from apix_core.models import Role as RoleEnum

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from datetime import date, datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from apix_api.auth import Role


class LatestValueRow(TypedDict):
    """One row of :func:`latest_values_multi` / :func:`latest_values`."""

    series_id: uuid.UUID
    period: date
    value: Decimal
    n_quotes: int
    coverage_pct: Decimal | None
    index_run_id: uuid.UUID
    released_at: datetime | None
    revision_count: int


class SeriesInfo(TypedDict):
    """One row of :func:`get_series_ids_by_prefix`."""

    code: str
    dimensions: dict[str, str]


async def get_series_id(session: AsyncSession, series_code: str) -> uuid.UUID | None:
    return (
        await session.execute(select(Series.id).where(Series.code == series_code))
    ).scalar_one_or_none()


async def get_series_ids_by_prefix(
    session: AsyncSession, like_pattern: str
) -> dict[uuid.UUID, SeriesInfo]:
    """``series.id -> {"code": ..., "dimensions": ...}`` for every series matching a
    SQL ``LIKE`` pattern, e.g. ``"APIX.ROUTE.%.M"``.
    """
    rows = (
        await session.execute(
            select(Series.id, Series.code, Series.dimensions).where(Series.code.like(like_pattern))
        )
    ).all()
    return {sid: SeriesInfo(code=code, dimensions=dimensions) for sid, code, dimensions in rows}


def visible_runs_filter(role: Role) -> ColumnElement[bool]:
    """Public callers only ever see released runs; researcher/official see everything."""
    if role is RoleEnum.PUBLIC:
        return IndexRun.released_at.isnot(None)
    return true()


async def latest_run_fingerprint(
    session: AsyncSession, series_ids: Sequence[uuid.UUID], *, role: Role
) -> str:
    """The most recently computed visible run touching any of ``series_ids`` — one
    cheap indexed query, used as the cache-invalidating component of a response cache
    key (``apix_api.cache``): a new run changes the fingerprint, so a cached response
    keyed on it is never served past the run that produced it. ``"none"`` when nothing
    has been published yet — still a valid, stable key.
    """
    if not series_ids:
        return "none"
    stmt = (
        select(IndexRun.id)
        .join(IndexValue, IndexValue.index_run_id == IndexRun.id)
        .where(IndexValue.series_id.in_(series_ids), visible_runs_filter(role))
        .order_by(IndexRun.computed_at.desc())
        .limit(1)
    )
    run_id = (await session.execute(stmt)).scalar_one_or_none()
    return str(run_id) if run_id is not None else "none"


async def latest_values_multi(
    session: AsyncSession,
    series_ids: Sequence[uuid.UUID],
    *,
    role: Role,
    from_period: date | None = None,
    to_period: date | None = None,
) -> list[LatestValueRow]:
    """The current best estimate for every (series, period) among ``series_ids``: the
    value from the most recent visible run that published that period (highest
    ``vintage_date``, ties broken by ``computed_at``), in one query regardless of how
    many series are requested.

    Returns one dict per (series, period), with ``series_id``, ``period``, ``value``,
    ``n_quotes``, ``coverage_pct``, ``index_run_id``, ``released_at`` and
    ``revision_count`` (> 0 means this period has been revised at least once —
    CLAUDE.md: revisions are visible, never silent).
    """
    if not series_ids:
        return []
    rank = (
        func.row_number()
        .over(
            partition_by=(IndexValue.series_id, IndexValue.period),
            order_by=(IndexRun.vintage_date.desc(), IndexRun.computed_at.desc()),
        )
        .label("rank")
    )
    stmt = (
        select(
            IndexValue.series_id,
            IndexValue.period,
            IndexValue.value,
            IndexValue.n_quotes,
            IndexValue.coverage_pct,
            IndexValue.index_run_id,
            IndexRun.released_at,
            rank,
        )
        .join(IndexRun, IndexRun.id == IndexValue.index_run_id)
        .where(IndexValue.series_id.in_(series_ids), visible_runs_filter(role))
    )
    if from_period is not None:
        stmt = stmt.where(IndexValue.period >= from_period)
    if to_period is not None:
        stmt = stmt.where(IndexValue.period <= to_period)

    latest = stmt.subquery()
    revisions = (
        select(
            RevisionLog.series_id,
            RevisionLog.period,
            func.count(RevisionLog.id).label("n"),
        )
        .where(RevisionLog.series_id.in_(series_ids))
        .group_by(RevisionLog.series_id, RevisionLog.period)
        .subquery()
    )
    final = (
        select(
            latest.c.series_id,
            latest.c.period,
            latest.c.value,
            latest.c.n_quotes,
            latest.c.coverage_pct,
            latest.c.index_run_id,
            latest.c.released_at,
            func.coalesce(revisions.c.n, 0).label("revision_count"),
        )
        .select_from(latest)
        .outerjoin(
            revisions,
            and_(
                revisions.c.series_id == latest.c.series_id,
                revisions.c.period == latest.c.period,
            ),
        )
        .where(latest.c.rank == 1)
        .order_by(latest.c.series_id, latest.c.period)
    )
    rows = (await session.execute(final)).mappings().all()
    return [LatestValueRow(**row) for row in rows]  # type: ignore[typeddict-item]


async def latest_values(
    session: AsyncSession,
    series_id: uuid.UUID,
    *,
    role: Role,
    from_period: date | None = None,
    to_period: date | None = None,
) -> list[LatestValueRow]:
    """Single-series convenience wrapper around :func:`latest_values_multi`."""
    return await latest_values_multi(
        session, [series_id], role=role, from_period=from_period, to_period=to_period
    )


async def imputed_run_periods(
    session: AsyncSession, series_id: uuid.UUID
) -> set[tuple[uuid.UUID, date]]:
    """``(index_run_id, period)`` pairs for one series where at least one linked
    cleaned quote was imputed — one query, checked in memory per row afterwards, so a
    caller listing many periods never issues one imputed-flag query per row.

    Only meaningful for series the index-run job links lineage for (the headline series
    and route-level series); a series with no tracked lineage never appears here, which
    callers must read as "not tracked", not as "nothing was imputed".
    """
    rows = (
        await session.execute(
            select(IndexValueQuote.index_run_id, IndexValueQuote.period)
            .join(FareQuoteClean, FareQuoteClean.id == IndexValueQuote.clean_id)
            .where(IndexValueQuote.series_id == series_id, FareQuoteClean.is_imputed.is_(True))
            .distinct()
        )
    ).all()
    return {(run_id, period) for run_id, period in rows}


__all__ = [
    "LatestValueRow",
    "SeriesInfo",
    "get_series_id",
    "get_series_ids_by_prefix",
    "imputed_run_periods",
    "latest_run_fingerprint",
    "latest_values",
    "latest_values_multi",
    "visible_runs_filter",
]
