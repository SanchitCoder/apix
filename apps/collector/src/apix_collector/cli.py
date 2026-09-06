"""``python -m apix_collector`` — CLI entrypoints. ``make collect-once`` calls this.

Runs the three spiders against the recorded fixtures under ``fixtures/`` for one
route, through the real ``PolicyEngine``, and writes ``collection_run``/``fare_quote``
rows with full provenance. Requires ``make up`` (Postgres + Redis) and ``make seed``
(sources, airports, carriers, the route basket) to have already run.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from typing import Any

import redis
import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apix_collector.fixtureserver import FixtureServer
from apix_collector.registry import build_spiders
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

log = structlog.get_logger(__name__)

#: A representative point on the advance-purchase curve for a demo run. A real sweep
#: (apix_scheduler.flows.daily_sweep) iterates every configured advance window.
_DEMO_ADVANCE_DAYS = 21


def collect_once(route_code: str, *, database_url: str | None = None) -> dict[str, Any]:
    """Run all three spiders once against fixtures, for ``route_code``. Returns a summary."""
    settings = get_settings()
    repo_root = find_config_dir().parent
    basket = load_basket()
    if route_code not in {route.code for route in basket.routes}:
        raise ValueError(f"{route_code!r} is not in the basket (config/basket.yaml)")

    engine = create_engine(database_url or settings.database_sync_url)
    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    summary: dict[str, Any] = {"succeeded": 0, "blocked": 0, "failed": 0, "quotes": 0}
    travel_date = datetime.now(UTC).date() + timedelta(days=_DEMO_ADVANCE_DAYS)

    try:
        decision_log = DatabaseDecisionLog(lambda: Session(engine))
        with (
            load_policy_engine(
                redis_client=redis_client,
                decision_log=decision_log,
                user_agent=settings.user_agent,
            ) as policy_engine,
            FixtureServer(repo_root / "fixtures") as server,
        ):
            browser_driver = PlaywrightBrowserDriver()
            try:
                spiders = build_spiders(
                    fixture_root_url=server.base_url,
                    policy_engine=policy_engine,
                    browser_driver=browser_driver,
                )
                object_store = LocalObjectStore(repo_root / "var" / "raw_payloads")
                with Session(engine) as session:
                    for spider in spiders:
                        result = run_spider_once(
                            spider,
                            route_code=route_code,
                            travel_date=travel_date,
                            advance_days=_DEMO_ADVANCE_DAYS,
                        )
                        persist_run_result(
                            session,
                            source_id=source_id_by_code(session, spider.source_code),
                            route_id=route_id_by_code(session, route_code, basket.basket_version),
                            result=result,
                            object_store=object_store,
                        )
                        summary[result.status.value.lower()] += 1
                        summary["quotes"] += len(result.quotes)
                        log.info(
                            "collector_spider_finished",
                            source=spider.source_code,
                            route=route_code,
                            status=result.status.value,
                            quotes=len(result.quotes),
                            error_class=result.error_class,
                        )
                    session.commit()
            finally:
                browser_driver.close()
    finally:
        engine.dispose()
        redis_client.close()
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="APIx collector CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser(
        "collect-once", help="run every spider once against fixtures for one route"
    )
    collect_parser.add_argument("--route", required=True, help="route code, e.g. DEL-BOM")

    args = parser.parse_args(argv)
    if args.command == "collect-once":
        summary = collect_once(args.route)
        log.info("collect_once_finished", route=args.route, **summary)
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via make collect-once
    raise SystemExit(main())
