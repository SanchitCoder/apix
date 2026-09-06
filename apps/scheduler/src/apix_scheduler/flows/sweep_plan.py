"""Pure planning logic for the daily sweep.

Kept free of Prefect, the database and the network so it can be tested directly: what
gets swept, and how the outcomes roll up into a coverage report, are ordinary
questions about ``BasketConfig`` and a list of results — no orchestration needed to
get them right.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from apix_core.config.basket import AdvanceWindow, BasketConfig, RouteEntry


@dataclass(frozen=True, slots=True)
class SweepCell:
    """One (source, route, advance window) the sweep collects for on ``sweep_date``."""

    source_code: str
    route_code: str
    window_code: str
    advance_days: int
    travel_date: date
    sweep_date: date


def advance_days_for_window(window: AdvanceWindow) -> int:
    """The representative advance-purchase point for one window: its midpoint.

    Collecting at every day in a wide window is future work; the midpoint gives one
    honest observation per stratum per sweep without inflating the request count by
    the window's width.
    """
    return (window.min_days + window.max_days) // 2


def active_routes(basket: BasketConfig, on: date) -> list[RouteEntry]:
    """Basket routes whose active window covers ``on``."""
    return [
        route
        for route in basket.routes
        if route.active_from <= on and (route.active_to is None or route.active_to > on)
    ]


def sweep_cells(
    basket: BasketConfig, source_codes: Sequence[str], sweep_date: date
) -> list[SweepCell]:
    """Every (source, route, window) cell the sweep should collect on ``sweep_date``."""
    routes = active_routes(basket, sweep_date)
    return [
        SweepCell(
            source_code=source_code,
            route_code=route.code,
            window_code=window.code,
            advance_days=(advance_days := advance_days_for_window(window)),
            travel_date=sweep_date + timedelta(days=advance_days),
            sweep_date=sweep_date,
        )
        for source_code in source_codes
        for route in routes
        for window in basket.advance_windows
    ]


@dataclass(frozen=True, slots=True)
class CoverageSummary:
    """A sweep's outcome, rolled up overall and per source."""

    total_cells: int
    succeeded: int
    blocked: int
    failed: int
    quotes: int
    by_source: dict[str, dict[str, int]]


def summarize_outcomes(outcomes: Iterable[Mapping[str, object]]) -> CoverageSummary:
    """Roll up per-cell outcomes (as produced by the collection task) into a report.

    Each outcome is expected to carry ``source_code``, ``status`` (one of
    ``succeeded``/``blocked``/``failed``, case-insensitive) and ``quotes``.
    """
    totals = {"succeeded": 0, "blocked": 0, "failed": 0, "quotes": 0}
    by_source: dict[str, dict[str, int]] = {}
    n = 0
    for outcome in outcomes:
        n += 1
        source_code = str(outcome["source_code"])
        status = str(outcome["status"]).lower()
        quotes = int(outcome["quotes"])  # type: ignore[call-overload]
        bucket = by_source.setdefault(
            source_code, {"succeeded": 0, "blocked": 0, "failed": 0, "quotes": 0}
        )
        if status in totals:
            totals[status] += 1
            bucket[status] += 1
        totals["quotes"] += quotes
        bucket["quotes"] += quotes
    return CoverageSummary(
        total_cells=n,
        succeeded=totals["succeeded"],
        blocked=totals["blocked"],
        failed=totals["failed"],
        quotes=totals["quotes"],
        by_source=by_source,
    )


__all__ = [
    "CoverageSummary",
    "SweepCell",
    "active_routes",
    "advance_days_for_window",
    "summarize_outcomes",
    "sweep_cells",
]
