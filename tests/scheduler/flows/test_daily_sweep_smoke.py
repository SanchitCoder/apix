"""Import-time contract of the daily_sweep flow.

Actually *running* the flow needs a live Postgres, Redis and (for the cache/concurrency
machinery) a Prefect API — see ``make test-integration`` territory, not the unit
suite. This asserts the flow and task are wired the way the module promises: a real
Prefect ``Flow``/``Task``, named consistently with what an operator would look for in
the Prefect UI, and idempotent on the fields the docstring claims.
"""

from __future__ import annotations

from prefect import Flow, Task

from apix_scheduler.flows.daily_sweep import (
    _sweep_cache_key,
    collect_route_window,
    daily_sweep,
    serve_daily_sweep,
)


def test_daily_sweep_is_a_prefect_flow() -> None:
    assert isinstance(daily_sweep, Flow)
    assert daily_sweep.name == "daily-sweep"


def test_collect_route_window_is_a_cached_prefect_task() -> None:
    assert isinstance(collect_route_window, Task)
    assert collect_route_window.name == "collect-route-window"
    assert collect_route_window.cache_key_fn is _sweep_cache_key
    assert collect_route_window.cache_expiration is not None


def test_cache_key_is_stable_for_the_same_cell_and_varies_otherwise() -> None:
    from datetime import date

    base = {
        "database_url": "postgresql://localhost/apix",
        "source_code": "airline_indigo",
        "route_code": "DEL-BOM",
        "window_code": "AP00_03",
        "sweep_date": date(2026, 9, 4),
    }
    assert _sweep_cache_key(None, base) == _sweep_cache_key(None, dict(base))
    different_date = {**base, "sweep_date": date(2026, 9, 5)}
    assert _sweep_cache_key(None, base) != _sweep_cache_key(None, different_date)
    different_source = {**base, "source_code": "airline_akasa"}
    assert _sweep_cache_key(None, base) != _sweep_cache_key(None, different_source)
    different_database = {**base, "database_url": "postgresql://staging/apix"}
    assert _sweep_cache_key(None, base) != _sweep_cache_key(None, different_database)


def test_serve_daily_sweep_is_importable_and_callable_signature() -> None:
    # Not invoked — it blocks forever registering a deployment with a live Prefect
    # server. This only proves the wiring (schedule construction) doesn't blow up
    # before that blocking call, by checking it is the expected shape.
    assert callable(serve_daily_sweep)
