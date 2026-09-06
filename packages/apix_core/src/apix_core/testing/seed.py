"""Seed a local database with the labelled synthetic dataset.

``make seed-synthetic DAYS=90`` runs this module. It generates the synthetic fare
surface (:mod:`apix_core.testing.synthetic`), loads the real reference data it hangs
off, inserts everything with source_type, collection_method and legal_basis all set to
``SYNTHETIC``, and writes the anomaly ground-truth file that detection tests assert
against.

It refuses — hard, with no override — to touch anything that is not unmistakably a
local development database. Synthetic rows in a production ``fare_quote`` would be the
exact contamination this system exists to make impossible.
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apix_core.config import config_hash, find_config_dir, load_basket, load_synthetic
from apix_core.models.collection import CollectionRun, Source
from apix_core.models.enums import RunStatus, SourceType
from apix_core.models.quotes import FareQuote
from apix_core.models.reference import Route
from apix_core.provenance.hashing import hash_url, sha256_hex
from apix_core.seeding.reference import load_airport_coords, seed_reference
from apix_core.settings import Environment, get_settings
from apix_core.testing.synthetic import SYNTHETIC_UUID_NAMESPACE, SyntheticDataset, generate

if TYPE_CHECKING:
    from pathlib import Path

    import pandas as pd

    from apix_core.config.synthetic import SyntheticConfig

IST = timezone(timedelta(hours=5, minutes=30))

# Hosts that can plausibly be a developer's own database. Anything else is refused.
_LOCAL_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "postgres", "db", "timescaledb", "host.docker.internal"}
)

_INSERT_CHUNK = 5_000

log = structlog.get_logger(__name__)


class SyntheticSeedRefusedError(RuntimeError):
    """The target database is not demonstrably a local development database."""


def refuse_unsafe_database(url: str, env: Environment) -> None:
    """Refuse any target that is not unmistakably local. There is no override flag.

    Three independent checks, all required:

    * the process environment must be ``local`` or ``ci``;
    * the database host must be a loopback/compose-internal name (a unix socket, with
      no host at all, also passes);
    * neither host nor database name may contain ``prod`` — which catches the SSH
      tunnel that makes a production database answer on localhost.
    """
    if env not in (Environment.LOCAL, Environment.CI):
        raise SyntheticSeedRefusedError(
            f"APIX_ENV={env.value}: synthetic data is never seeded outside local/ci."
        )
    parsed = make_url(url)
    host = (parsed.host or "").lower()
    database = (parsed.database or "").lower()
    if host and host not in _LOCAL_HOSTS:
        raise SyntheticSeedRefusedError(
            f"database host {host!r} is not a local development host "
            f"({', '.join(sorted(_LOCAL_HOSTS))}). Refusing to write synthetic data."
        )
    if "prod" in host or "prod" in database:
        raise SyntheticSeedRefusedError(
            f"database {host!r}/{database!r} looks like production. Refusing to write "
            "synthetic data, even via a local tunnel."
        )


def _quote_content_hash(record: dict[str, Any]) -> str:
    """Hash of the displayed quote, from its canonical JSON form."""
    payload = {
        key: str(record[key])
        for key in (
            "source_code",
            "route_code",
            "carrier_iata",
            "flight_number",
            "query_date",
            "travel_date",
            "base_fare",
            "taxes",
            "udf",
            "convenience_fee",
            "total_fare",
        )
    }
    return sha256_hex(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _money(value: float) -> Decimal:
    return Decimal(f"{value:.2f}")


def _run_id(source_code: str, query_date: date) -> uuid.UUID:
    return uuid.uuid5(SYNTHETIC_UUID_NAMESPACE, f"run|{source_code}|{query_date.isoformat()}")


def _collected_at(query_date: date, hour_ist: int) -> datetime:
    return datetime.combine(query_date, time(hour=hour_ist, tzinfo=IST))


def _source_rows(cfg: SyntheticConfig) -> list[dict[str, Any]]:
    return [
        {
            "id": uuid.uuid5(SYNTHETIC_UUID_NAMESPACE, f"source|{source.code}"),
            "code": source.code,
            "display_name": source.display_name,
            "domain": f"{source.code}.invalid",  # RFC 2606: can never resolve
            "source_type": SourceType.SYNTHETIC.value,
            "enabled": False,  # nothing ever collects from a synthetic source
        }
        for source in cfg.sources
    ]


def _collection_run_rows(cfg: SyntheticConfig, quotes: pd.DataFrame) -> list[dict[str, Any]]:
    """One SUCCEEDED run per (channel, collection day), carrying its quote count."""
    counts = quotes.groupby(["source_code", "query_date"]).size()
    rows: list[dict[str, Any]] = []
    for (source_code, query_date), n in counts.items():
        started = _collected_at(query_date, cfg.collection.collection_hour_ist)
        rows.append(
            {
                "id": _run_id(str(source_code), query_date),
                "source_id": uuid.uuid5(SYNTHETIC_UUID_NAMESPACE, f"source|{source_code}"),
                "route_id": None,
                "started_at": started,
                "finished_at": started + timedelta(minutes=30),
                "status": RunStatus.SUCCEEDED.value,
                "quotes_collected": int(n),
                "blocked_count": 0,
                "error_class": None,
                "error_detail": None,
            }
        )
    return rows


def _quote_records(
    cfg: SyntheticConfig, dataset: SyntheticDataset, route_ids: dict[str, uuid.UUID]
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    hour = cfg.collection.collection_hour_ist
    for row in dataset.quotes.itertuples(index=False):
        record: dict[str, Any] = {
            "id": row.id,
            "collected_at": _collected_at(row.query_date, hour),
            "run_id": _run_id(row.source_code, row.query_date),
            "source_id": uuid.uuid5(SYNTHETIC_UUID_NAMESPACE, f"source|{row.source_code}"),
            "collection_method": "SYNTHETIC",
            "legal_basis": "SYNTHETIC",
            "source_url_hash": hash_url(
                f"https://{row.source_code}.invalid/fares?route={row.route_code}"
                f"&travel={row.travel_date}&query={row.query_date}"
            ),
            "raw_payload_ref": None,
            "route_id": route_ids[row.route_code],
            "carrier_iata": row.carrier_iata,
            "flight_number": row.flight_number,
            "dep_datetime_local": row.dep_datetime_local.to_pydatetime(),
            "arr_datetime_local": row.arr_datetime_local.to_pydatetime(),
            "stops": 0,
            "travel_date": row.travel_date,
            "query_date": row.query_date,
            "advance_days": int(row.advance_days),
            "fare_class": "ECONOMY",
            "fare_brand": f"SYNTH-B{int(row.fare_bucket)}",
            "base_fare": _money(row.base_fare),
            "taxes": _money(row.taxes),
            "udf": _money(row.udf),
            "convenience_fee": _money(row.convenience_fee),
            "total_fare": _money(row.total_fare),
            "currency": "INR",
            "seats_shown": int(row.seats_shown),
            "refundable": bool(row.refundable),
            "baggage_included": True,
        }
        record["content_hash"] = _quote_content_hash(
            {
                **record,
                "source_code": row.source_code,
                "route_code": row.route_code,
            }
        )
        records.append(record)
    return records


def _write_ground_truth(
    path: Path, cfg: SyntheticConfig, dataset: SyntheticDataset, quote_count: int
) -> None:
    """The deterministic ground-truth file tests assert anomaly detection against."""
    sold_by_adv = dataset.sold_out.groupby("advance_days").size()
    payload = {
        "dataset": "apix-synthetic-ground-truth",
        "warning": (
            "SYNTHETIC scenario data. Every fare in the associated rows was generated "
            "by apix_core.testing.synthetic; nothing here was collected from any "
            "source. The anomalies below were injected deliberately."
        ),
        "seed": dataset.seed,
        "config_version": cfg.version,
        "config_hash": config_hash(cfg),
        "start_query_date": dataset.start_query_date.isoformat(),
        "days": dataset.days,
        "quote_count": quote_count,
        "sold_out_count": len(dataset.sold_out),
        "sold_out_by_advance_days": {str(k): int(v) for k, v in sold_by_adv.items()},
        "anomaly_count": len(dataset.anomalies),
        "anomalies": dataset.anomalies.to_dict(orient="records"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    sold_out_path = path.with_name("sold_out_cells.csv")
    dataset.sold_out.to_csv(sold_out_path, index=False)


def seed_synthetic(
    database_url: str,
    days: int,
    start_query_date: date,
    repo_root: Path,
) -> dict[str, int]:
    """Generate and persist the synthetic dataset. Returns row counts by table."""
    settings = get_settings()
    refuse_unsafe_database(database_url, settings.env)

    config_dir = find_config_dir()
    cfg = load_synthetic(config_dir)
    basket = load_basket(config_dir)
    seeds_dir = repo_root / "db" / "seeds"

    log.info(
        "synthetic_generation_started",
        seed=cfg.seed,
        days=days,
        start_query_date=start_query_date.isoformat(),
    )
    dataset = generate(cfg, basket, load_airport_coords(seeds_dir), start_query_date, days)

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            counts = seed_reference(session, seeds_dir, basket)
            session.execute(pg_insert(Source).values(_source_rows(cfg)).on_conflict_do_nothing())
            session.execute(
                pg_insert(CollectionRun)
                .values(_collection_run_rows(cfg, dataset.quotes))
                .on_conflict_do_nothing()
            )
            route_pairs = (
                session.execute(
                    select(Route.code, Route.id).where(
                        Route.basket_version == basket.basket_version
                    )
                )
                .tuples()
                .all()
            )
            route_ids: dict[str, uuid.UUID] = dict(route_pairs)
            records = _quote_records(cfg, dataset, route_ids)

            # fare_quote carries the append-only rules, and Postgres refuses
            # ON CONFLICT on a table with rules. Idempotency comes from the
            # deterministic ids instead: rows already present are skipped, never
            # rewritten — which is also the only treatment the table permits.
            inserted = 0
            already_present = 0
            for offset in range(0, len(records), _INSERT_CHUNK):
                chunk = records[offset : offset + _INSERT_CHUNK]
                existing = set(
                    session.scalars(
                        select(FareQuote.id).where(
                            FareQuote.id.in_([record["id"] for record in chunk])
                        )
                    )
                )
                new_records = [record for record in chunk if record["id"] not in existing]
                already_present += len(existing)
                if new_records:
                    session.execute(pg_insert(FareQuote).values(new_records))
                    inserted += len(new_records)
            session.commit()
    finally:
        engine.dispose()

    ground_truth_path = repo_root / "fixtures" / "synthetic" / "anomaly_ground_truth.json"
    _write_ground_truth(ground_truth_path, cfg, dataset, len(records))
    log.info(
        "synthetic_seed_finished",
        quotes=len(records),
        quotes_inserted=inserted,
        quotes_already_present=already_present,
        sold_out_cells=len(dataset.sold_out),
        anomalies=len(dataset.anomalies),
        airports=counts.airports,
        carriers=counts.carriers,
        routes=counts.routes,
        ground_truth=str(ground_truth_path),
    )
    return {
        "quotes": len(records),
        "sold_out_cells": len(dataset.sold_out),
        "anomalies": len(dataset.anomalies),
        "routes": counts.routes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed a LOCAL database with the labelled synthetic fare dataset."
    )
    parser.add_argument("--days", type=int, default=90, help="collection days to generate")
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=None,
        help="first collection date (default: today minus DAYS, so the window ends now)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="target database (default: APIX_DATABASE_SYNC_URL). Same guard applies.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    database_url = args.database_url or settings.database_sync_url
    start = args.start or (datetime.now(UTC).date() - timedelta(days=args.days))
    repo_root = find_config_dir().parent

    seed_synthetic(database_url, args.days, start, repo_root)
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via the integration test
    raise SystemExit(main())
