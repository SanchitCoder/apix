from __future__ import annotations

from datetime import date

from apix_core.config import load_basket
from apix_core.config.basket import AdvanceWindow, BasketConfig, RouteEntry
from apix_scheduler.flows.sweep_plan import (
    active_routes,
    advance_days_for_window,
    summarize_outcomes,
    sweep_cells,
)


def _window(code: str, min_days: int, max_days: int) -> AdvanceWindow:
    return AdvanceWindow(code=code, min_days=min_days, max_days=max_days, label=code)


def _route(code: str, origin: str, dest: str, active_to: date | None = None) -> RouteEntry:
    return RouteEntry(
        code=code, origin=origin, dest=dest, active_from=date(2026, 1, 1), active_to=active_to
    )


def test_advance_days_for_window_is_the_midpoint() -> None:
    assert advance_days_for_window(_window("AP00_03", 0, 3)) == 1
    assert advance_days_for_window(_window("AP08_14", 8, 14)) == 11


def test_active_routes_excludes_expired_ones() -> None:
    basket = BasketConfig(
        basket_version="test",
        effective_from=date(2026, 1, 1),
        advance_windows=[_window("W", 0, 7)],
        routes=[
            _route("DEL-BOM", "DEL", "BOM"),
            _route("BOM-DEL", "BOM", "DEL", active_to=date(2026, 6, 1)),
        ],
    )
    on = date(2026, 9, 4)
    assert [r.code for r in active_routes(basket, on)] == ["DEL-BOM"]


def test_sweep_cells_is_the_full_cross_product() -> None:
    basket = BasketConfig(
        basket_version="test",
        effective_from=date(2026, 1, 1),
        advance_windows=[_window("W1", 0, 3), _window("W2", 4, 7)],
        routes=[_route("DEL-BOM", "DEL", "BOM"), _route("BOM-DEL", "BOM", "DEL")],
    )
    sweep_date = date(2026, 9, 4)
    cells = sweep_cells(basket, ("source_a", "source_b"), sweep_date)
    assert len(cells) == 2 * 2 * 2  # sources x routes x windows
    cell = next(
        c
        for c in cells
        if c.source_code == "source_a" and c.route_code == "DEL-BOM" and c.window_code == "W1"
    )
    assert cell.advance_days == 1
    assert cell.travel_date == date(2026, 9, 5)
    assert cell.sweep_date == sweep_date


def test_sweep_cells_against_the_real_basket_is_non_empty(config_dir) -> None:
    basket = load_basket(config_dir)
    cells = sweep_cells(basket, ("airline_indigo",), date(2026, 9, 4))
    assert len(cells) == len(basket.routes) * len(basket.advance_windows)


def test_summarize_outcomes_rolls_up_overall_and_per_source() -> None:
    outcomes = [
        {"source_code": "a", "status": "SUCCEEDED", "quotes": 3},
        {"source_code": "a", "status": "BLOCKED", "quotes": 0},
        {"source_code": "b", "status": "FAILED", "quotes": 0},
        {"source_code": "b", "status": "SUCCEEDED", "quotes": 5},
    ]
    summary = summarize_outcomes(outcomes)
    assert summary.total_cells == 4
    assert summary.succeeded == 2
    assert summary.blocked == 1
    assert summary.failed == 1
    assert summary.quotes == 8
    assert summary.by_source["a"] == {"succeeded": 1, "blocked": 1, "failed": 0, "quotes": 3}
    assert summary.by_source["b"] == {"succeeded": 1, "blocked": 0, "failed": 1, "quotes": 5}


def test_summarize_outcomes_of_nothing_is_all_zero() -> None:
    summary = summarize_outcomes([])
    assert summary.total_cells == 0
    assert summary.by_source == {}
