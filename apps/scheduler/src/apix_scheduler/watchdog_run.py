"""``python -m apix_scheduler.watchdog_run``.

``make watchdog-probe`` / ``make watchdog-report`` call this. Two subcommands:

* ``probe`` — the personalised-pricing probe. Checks
  :func:`apix_core.watchdog.can_run_probe_now` first (on top of the per-source Redis
  rate limiter every individual request already passes through inside
  ``PolicyEngine``), then issues the identical query through N session profiles via
  :mod:`apix_collector.personalisation.probe`, persists
  ``personalisation_probe_observation`` + ``dispersion_stat`` rows. Phase 1 probes a
  single fixture-backed source (``airline_indigo``) and a single configured route —
  the same "only fixture_replay is actually reachable today" reality every other
  collection path in this repo already lives with.
* ``report`` — surge detection + sell-out velocity + rail comparison, computed on
  demand from real ``fare_quote``/``fare_quote_clean`` data and logged via structlog.
  Nothing here is persisted: both are cheap to recompute, and neither carries the same
  past-vintage auditability requirement a raw observation does (see
  ``apix_core.models.watchdog``'s module docstring).
"""

from __future__ import annotations

import argparse
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pandas as pd
import redis
import structlog
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from apix_collector.fixtureserver import FixtureServer
from apix_collector.personalisation.probe import ProfileRunResult, build_profiles, run_probe
from apix_collector.spiders.indigo import IndigoSpider
from apix_core.clean.missing import CELL_IDENTITY, classify_missing_cells, with_carrier_type
from apix_core.config import find_config_dir, load_basket, load_watchdog
from apix_core.models import (
    CollectionRun,
    DispersionStat,
    PersonalisationProbeObservation,
    Route,
    Source,
)
from apix_core.models.enums import LegalBasis
from apix_core.policy import DatabaseDecisionLog, load_policy_engine
from apix_core.provenance.hashing import sha256_hex
from apix_core.seeding.reference import read_seed_csv
from apix_core.settings import get_settings
from apix_core.watchdog import (
    can_run_probe_now,
    compute_dispersion,
    compute_sellout_velocity,
    detect_surges,
)

# Reused rather than duplicated: the sampling-grid and collection-run loading logic is
# identical to what a real index run needs, and lives there already. This is an
# internal (leading-underscore) import within the same app package, not a public
# apix_scheduler.index_run contract.
from apix_scheduler.index_run import (
    _build_expected_cells,
    _load_collection_runs,
    _load_window_quotes,
)

if TYPE_CHECKING:
    from pathlib import Path

    from apix_collector.session import SessionRotator

log = structlog.get_logger(__name__)

#: Phase 1 probes one route and one fixture-backed source. A real deployment would
#: sweep every route in config/watchdog.yaml's personalisation_probe.routes; that is
#: orchestration this repo does not have yet (see apix_scheduler.flows.daily_sweep for
#: the pattern a later phase would extend).
_PROBE_SOURCE_CODE = IndigoSpider.source_code
_PROBE_ADVANCE_DAYS = 21


# ------------------------------------------------------------------ probe ----


def _observations_frame(
    source_code: str, probed_at: datetime, profile_results: list[ProfileRunResult]
) -> pd.DataFrame:
    rows = [
        {
            "source_code": source_code,
            "flight_key": (
                f"{raw.carrier_iata}-{raw.flight_number}-{pr.result.travel_date.isoformat()}"
            ),
            "probed_at": probed_at,
            "session_id": pr.profile.session_id,
            "total_fare": float(raw.total_fare),
        }
        for pr in profile_results
        for raw in pr.result.quotes
    ]
    return pd.DataFrame(
        rows, columns=["source_code", "flight_key", "probed_at", "session_id", "total_fare"]
    )


def _persist_probe_run(
    session: Session,
    *,
    source_id: uuid.UUID,
    route_id: uuid.UUID,
    probed_at: datetime,
    profile_results: list[ProfileRunResult],
) -> tuple[int, int]:
    """Write one ``collection_run`` per profile, one
    ``personalisation_probe_observation`` per quote, and the computed
    ``dispersion_stat`` rows. Returns ``(n_observations, n_dispersion_rows)``.
    """
    n_observations = 0
    for profile_result in profile_results:
        result = profile_result.result
        profile = profile_result.profile
        run = CollectionRun(
            source_id=source_id,
            route_id=route_id,
            finished_at=datetime.now(UTC),
            status=result.status,
            quotes_collected=len(result.quotes),
            blocked_count=result.blocked_count,
            error_class=result.error_class,
            error_detail=result.error_detail,
        )
        session.add(run)
        session.flush()
        for raw in result.quotes:
            assert result.payload is not None and result.collection_method is not None
            flight_key = f"{raw.carrier_iata}-{raw.flight_number}-{result.travel_date.isoformat()}"
            content_hash = sha256_hex(
                f"{profile.session_id}:{flight_key}:{raw.total_fare}".encode()
            )
            session.add(
                PersonalisationProbeObservation(
                    id=uuid.uuid4(),
                    probed_at=probed_at,
                    run_id=run.id,
                    source_id=source_id,
                    collection_method=result.collection_method,
                    legal_basis=LegalBasis.FIXTURE,
                    content_hash=content_hash,
                    raw_payload_ref=None,
                    route_id=route_id,
                    flight_key=flight_key,
                    session_id=profile.session_id,
                    cookie_state=profile.cookie_state,
                    ua_class=profile.ua_class,
                    geography_tag=profile.geography,
                    total_fare=raw.total_fare,
                )
            )
            n_observations += 1

    frame = _observations_frame(_PROBE_SOURCE_CODE, probed_at, profile_results)
    n_dispersion_rows = 0
    if not frame.empty:
        dispersion = compute_dispersion(frame)
        for _, row in dispersion.iterrows():
            session.add(
                DispersionStat(
                    id=uuid.uuid4(),
                    source_id=source_id,
                    flight_key=row["flight_key"],
                    probed_at=row["probed_at"],
                    statistic_name=row["statistic_name"],
                    value=Decimal(str(round(float(row["value"]), 2))),
                    n_sessions=int(row["n_sessions"]),
                )
            )
            n_dispersion_rows += 1
    return n_observations, n_dispersion_rows


def run_probe_command(
    session: Session, repo_root: Path, database_url: str, now: datetime | None = None
) -> dict[str, Any]:
    """The full probe: frequency gate, N-profile collection, persistence. Returns a
    summary dict for logging.
    """
    now = now or datetime.now(UTC)
    config_dir = find_config_dir()
    watchdog_cfg = load_watchdog(config_dir)
    probe_cfg = watchdog_cfg.personalisation_probe
    basket = load_basket(config_dir)

    last_run_at = session.execute(
        select(func.max(PersonalisationProbeObservation.probed_at))
    ).scalar()
    if not can_run_probe_now(last_run_at, probe_cfg.min_interval_hours, now):
        log.info(
            "watchdog_probe_skipped_too_soon",
            last_run_at=last_run_at.isoformat() if last_run_at else None,
            min_interval_hours=probe_cfg.min_interval_hours,
        )
        return {"skipped": True, "observations": 0, "dispersion_rows": 0}

    route_code = probe_cfg.routes[0]
    if route_code not in {r.code for r in basket.routes}:
        raise ValueError(f"{route_code!r} is not in the basket (config/basket.yaml)")
    source_id = session.execute(
        select(Source.id).where(Source.code == _PROBE_SOURCE_CODE)
    ).scalar_one()
    route_id = session.execute(
        select(Route.id).where(
            Route.code == route_code, Route.basket_version == basket.basket_version
        )
    ).scalar_one()

    profiles = build_profiles(probe_cfg)
    travel_date = now.date() + timedelta(days=_PROBE_ADVANCE_DAYS)

    settings = get_settings()
    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        decision_log = DatabaseDecisionLog(lambda: Session(create_engine(database_url)))
        with (
            load_policy_engine(
                redis_client=redis_client, decision_log=decision_log, user_agent=settings.user_agent
            ) as policy_engine,
            FixtureServer(repo_root / "fixtures") as server,
        ):
            fixture_base_url = f"{server.base_url}/{_PROBE_SOURCE_CODE}"

            def factory(rotator: SessionRotator) -> IndigoSpider:
                return IndigoSpider(
                    fixture_base_url=fixture_base_url,
                    policy_engine=policy_engine,
                    session_rotator=rotator,
                )

            profile_results = run_probe(
                factory,
                profiles,
                route_code=route_code,
                travel_date=travel_date,
                advance_days=_PROBE_ADVANCE_DAYS,
            )
    finally:
        redis_client.close()

    n_observations, n_dispersion_rows = _persist_probe_run(
        session,
        source_id=source_id,
        route_id=route_id,
        probed_at=now,
        profile_results=profile_results,
    )
    session.commit()
    return {
        "skipped": False,
        "profiles": len(profiles),
        "observations": n_observations,
        "dispersion_rows": n_dispersion_rows,
    }


# ------------------------------------------------------------------ report ----


def run_report(session: Session, as_of: datetime, days: int) -> None:
    """Surge + sell-out + rail, computed on demand and logged. Writes nothing."""
    config_dir = find_config_dir()
    watchdog_cfg = load_watchdog(config_dir)
    seeds_dir = config_dir.parent / "db" / "seeds"
    carrier_type_by_iata = {
        row["iata"]: row["carrier_type"] for row in read_seed_csv(seeds_dir / "carriers.csv")
    }

    as_of_date = as_of.date()
    start_query_date = as_of_date - timedelta(days=days - 1)
    quotes = _load_window_quotes(session, start_query_date, as_of_date)
    if quotes.empty:
        log.info("watchdog_report_no_quotes", as_of=as_of_date.isoformat())
        return

    daily = (
        quotes.groupby(["route_code", "travel_date"])["total_fare"]
        .median()
        .reset_index()
        .rename(columns={"total_fare": "fare"})
    )
    surges = detect_surges(daily, watchdog_cfg.surge)
    flagged = surges.loc[surges["is_surge"]]
    log.info(
        "watchdog_report_surge",
        as_of=as_of_date.isoformat(),
        n_cells=len(surges),
        n_flagged=len(flagged),
        examples=flagged.head(10).to_dict(orient="records"),
    )

    collection_runs = _load_collection_runs(session, start_query_date, as_of_date)
    expected_cells = _build_expected_cells(quotes, collection_runs)
    if expected_cells.empty:
        log.info("watchdog_report_sellout_no_expected_cells", as_of=as_of_date.isoformat())
    else:
        missing = classify_missing_cells(
            expected_cells, quotes[list(CELL_IDENTITY)], collection_runs
        )
        missing = with_carrier_type(missing, carrier_type_by_iata)
        velocity = compute_sellout_velocity(missing, watchdog_cfg.sellout.min_group_size)
        log.info(
            "watchdog_report_sellout",
            as_of=as_of_date.isoformat(),
            n_groups=len(velocity),
            examples=velocity.head(10).to_dict(orient="records"),
        )

    if watchdog_cfg.rail.enabled and watchdog_cfg.rail.corridor_map:
        log.info(
            "watchdog_report_rail_not_implemented",
            reason="NotImplementedRailFareSource — no real rail-fare feed integrated yet, "
            "see docs/data-sources.md",
        )
    else:
        log.info(
            "watchdog_report_rail_disabled", reason="config/watchdog.yaml rail.enabled is false"
        )


# -------------------------------------------------------------------- CLI ----


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="APIx watchdog CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe_parser = subparsers.add_parser("probe", help="run the personalised-pricing probe")
    probe_parser.add_argument("--database-url", default=None)

    report_parser = subparsers.add_parser("report", help="surge + sell-out + rail report")
    report_parser.add_argument("--days", type=int, default=21)
    report_parser.add_argument("--database-url", default=None)

    args = parser.parse_args(argv)
    settings = get_settings()
    database_url = args.database_url or settings.database_sync_url
    engine = create_engine(database_url)
    repo_root = find_config_dir().parent
    try:
        with Session(engine) as session:
            if args.command == "probe":
                summary = run_probe_command(session, repo_root, database_url)
                log.info("watchdog_probe_finished", **summary)
            elif args.command == "report":
                run_report(session, datetime.now(UTC), args.days)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via make watchdog-probe/report
    raise SystemExit(main())
