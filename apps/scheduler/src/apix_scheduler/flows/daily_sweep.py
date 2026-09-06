"""``daily_sweep``: collect every active route x advance window x enabled source.

Idempotency
-----------
Re-running the flow for a sweep date that has already run must not duplicate quotes.
Each collection task's Prefect result cache key is
``(source_code, route_code, window_code, sweep_date)``, with a 20-hour expiration —
long enough that re-invoking today's sweep is a no-op, short enough that tomorrow's
sweep (a new ``sweep_date``) always runs. This is a property of the *flow*, not of the
database: ``fare_quote`` is append-only with no ``ON CONFLICT`` target it can use for
row-level dedup (see ``apix_core.testing.seed`` for why), so idempotency has to mean
"the same task body never runs twice for the same cell", not "a duplicate row gets
silently discarded".

Concurrency
-----------
Each task acquires a Prefect concurrency slot named ``apix-source-<code>`` before
collecting, so multiple routes for the same source are not driven in parallel beyond
whatever limit an operator has provisioned (``prefect concurrency-limit create
apix-source-airline_indigo 2``, for example). Absent a provisioned limit this is a
no-op (``concurrency(..., strict=False)``) — the PolicyEngine's own per-domain rate
limiter is still the hard backstop either way.

Scheduling
----------
:func:`serve_daily_sweep` registers four Cron schedules (configurable local times,
default IST) as one deployment. Jitter is applied inside the flow itself, once, before
any collection starts — not per task — so "four sweeps a day, jittered" means the
whole sweep starts at a randomised offset from its scheduled time, not that each of
its hundreds of cells starts at a different random moment.
"""

from __future__ import annotations

import random
import time
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import redis
import structlog
from prefect import flow, task
from prefect.concurrency.sync import concurrency
from prefect.schedules import Cron
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apix_collector.fixtureserver import FixtureServer
from apix_collector.registry import SOURCE_CODES, build_spiders
from apix_collector.run import (
    persist_run_result,
    route_id_by_code,
    run_spider_once,
    source_id_by_code,
)
from apix_collector.strategies.rendered_page import PlaywrightBrowserDriver
from apix_core.config import find_config_dir, load_basket
from apix_core.policy import DatabaseDecisionLog, load_policy_engine
from apix_core.provenance.store import LocalObjectStore
from apix_core.settings import get_settings
from apix_scheduler.flows.sweep_plan import CoverageSummary, summarize_outcomes, sweep_cells

if TYPE_CHECKING:
    from collections.abc import Sequence

    from prefect.context import TaskRunContext

    from apix_collector.spiders.base import BaseSpider

log = structlog.get_logger(__name__)

_CACHE_EXPIRATION_HOURS = 20
_DEFAULT_SWEEP_TIMES: tuple[str, ...] = ("02:00", "08:00", "14:00", "20:00")
_DEFAULT_TIMEZONE = "Asia/Kolkata"


def _sweep_cache_key(_context: TaskRunContext, parameters: dict[str, Any]) -> str:
    """One cache entry per (database, source, route, window, sweep_date).

    Prefect's default result storage is a local filesystem path, independent of which
    database the flow happens to be configured against — it persists across runs *and*
    across processes. Without ``database_url`` in the key, pointing the same flow at a
    fresh or different database within the cache window would report a task
    ``Cached``/succeeded without its ``persist_run_result`` write ever touching the new
    database: a silent gap between what the cache claims and what is actually in the
    target database (exactly what CLAUDE.md principle 2 forbids). Keying on the
    database too means a new target is simply a cache miss, not a false hit.
    """
    return (
        f"{parameters['database_url']}|{parameters['source_code']}|{parameters['route_code']}|"
        f"{parameters['window_code']}|{parameters['sweep_date'].isoformat()}"
    )


@task(
    name="collect-route-window",
    cache_key_fn=_sweep_cache_key,
    cache_expiration=timedelta(hours=_CACHE_EXPIRATION_HOURS),
    retries=0,  # BaseSpider already retries transient failures internally
)
def collect_route_window(
    *,
    spider: BaseSpider,
    source_code: str,
    route_code: str,
    window_code: str,
    advance_days: int,
    travel_date: date,
    sweep_date: date,  # noqa: ARG001 — unused in the body; Prefect binds it for _sweep_cache_key
    database_url: str,
    basket_version: str,
    object_store: LocalObjectStore,
) -> dict[str, Any]:
    """Collect one cell and persist it. Returns a small, JSON-serialisable outcome."""
    with concurrency([f"apix-source-{source_code}"], occupy=1, strict=False):
        result = run_spider_once(
            spider, route_code=route_code, travel_date=travel_date, advance_days=advance_days
        )

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            persist_run_result(
                session,
                source_id=source_id_by_code(session, source_code),
                route_id=route_id_by_code(session, route_code, basket_version),
                result=result,
                object_store=object_store,
            )
            session.commit()
    finally:
        engine.dispose()

    return {
        "source_code": source_code,
        "route_code": route_code,
        "window_code": window_code,
        "status": result.status.value,
        "quotes": len(result.quotes),
        "error_class": result.error_class,
    }


@flow(name="daily-sweep", log_prints=True)
def daily_sweep(sweep_date: date | None = None, jitter_minutes: int = 0) -> CoverageSummary:
    """Collect every active route x advance window x enabled source for ``sweep_date``.

    ``jitter_minutes`` sleeps a random ``[0, jitter_minutes)`` minutes before starting
    — the scheduled deployment passes a non-zero value; ad-hoc and test invocations
    leave it at 0 so calling this function never blocks unexpectedly.
    """
    if jitter_minutes > 0:
        delay_s = random.Random().uniform(0, jitter_minutes * 60)  # noqa: S311 — schedule jitter
        log.info("daily_sweep_jitter_sleep", delay_s=round(delay_s, 1))
        time.sleep(delay_s)

    settings = get_settings()
    repo_root = find_config_dir().parent
    basket = load_basket()
    sweep_date = sweep_date or datetime.now(UTC).date()

    engine = create_engine(settings.database_sync_url)
    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    object_store = LocalObjectStore(repo_root / "var" / "raw_payloads")
    decision_log = DatabaseDecisionLog(lambda: Session(engine))

    cells = sweep_cells(basket, SOURCE_CODES, sweep_date)
    log.info(
        "daily_sweep_started",
        sweep_date=sweep_date.isoformat(),
        cells=len(cells),
        sources=list(SOURCE_CODES),
    )

    try:
        with (
            load_policy_engine(
                redis_client=redis_client, decision_log=decision_log, user_agent=settings.user_agent
            ) as policy_engine,
            FixtureServer(repo_root / "fixtures") as server,
        ):
            browser_driver = PlaywrightBrowserDriver()
            try:
                spiders_by_source = {
                    spider.source_code: spider
                    for spider in build_spiders(
                        fixture_root_url=server.base_url,
                        policy_engine=policy_engine,
                        browser_driver=browser_driver,
                    )
                }
                futures = [
                    collect_route_window.submit(
                        spider=spiders_by_source[cell.source_code],
                        source_code=cell.source_code,
                        route_code=cell.route_code,
                        window_code=cell.window_code,
                        advance_days=cell.advance_days,
                        travel_date=cell.travel_date,
                        sweep_date=cell.sweep_date,
                        database_url=settings.database_sync_url,
                        basket_version=basket.basket_version,
                        object_store=object_store,
                    )
                    for cell in cells
                ]
                outcomes = [future.result() for future in futures]
            finally:
                browser_driver.close()
    finally:
        engine.dispose()
        redis_client.close()

    coverage = summarize_outcomes(outcomes)
    log.info(
        "daily_sweep_finished",
        sweep_date=sweep_date.isoformat(),
        total_cells=coverage.total_cells,
        succeeded=coverage.succeeded,
        blocked=coverage.blocked,
        failed=coverage.failed,
        quotes=coverage.quotes,
        by_source=coverage.by_source,
    )
    return coverage


def serve_daily_sweep(
    sweep_times: Sequence[str] = _DEFAULT_SWEEP_TIMES,
    timezone: str = _DEFAULT_TIMEZONE,
    jitter_minutes: int = 15,
) -> None:
    """Register ``daily_sweep`` on four Cron schedules and serve it. Blocks forever."""
    schedules = []
    for sweep_time in sweep_times:
        hour, minute = sweep_time.split(":")
        schedules.append(Cron(f"{int(minute)} {int(hour)} * * *", timezone=timezone))
    daily_sweep.serve(
        name="daily-sweep",
        schedules=schedules,
        parameters={"jitter_minutes": jitter_minutes},
    )


def main() -> None:  # pragma: no cover — exercised by running a Prefect worker
    serve_daily_sweep()


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["CoverageSummary", "collect_route_window", "daily_sweep", "main", "serve_daily_sweep"]
