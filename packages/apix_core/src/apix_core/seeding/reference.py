"""Reference data seeding: airports, carriers and the route basket.

Seed CSVs carry their provenance in ``#`` header comments, which the reader skips.
All inserts are idempotent (``ON CONFLICT DO NOTHING``): reference rows are only ever
added or corrected by new seed files plus a re-run, never silently mutated here.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from apix_core.models.reference import Airport, Carrier, Route

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

    from apix_core.config.basket import BasketConfig


@dataclass(frozen=True)
class ReferenceCounts:
    """How many rows each reference table holds after seeding."""

    airports: int
    carriers: int
    routes: int


def read_seed_csv(path: Path) -> list[dict[str, str]]:
    """Rows of a seed CSV, skipping the ``#`` provenance header."""
    with path.open(encoding="utf-8", newline="") as fh:
        lines = [line for line in fh if not line.startswith("#")]
    rows = list(csv.DictReader(lines))
    if not rows:
        raise ValueError(f"seed file {path} contains no data rows")
    return rows


def airport_rows(seeds_dir: Path) -> list[dict[str, Any]]:
    """``airport`` table rows from ``airports.csv``."""
    return [
        {
            "iata": row["iata"],
            "icao": row["icao"] or None,
            "name": row["name"],
            "city": row["city"],
            "state": row["state"] or None,
            "lat": Decimal(row["lat"]),
            "lon": Decimal(row["lon"]),
        }
        for row in read_seed_csv(seeds_dir / "airports.csv")
    ]


def carrier_rows(seeds_dir: Path) -> list[dict[str, Any]]:
    """``carrier`` table rows from ``carriers.csv``."""
    return [
        {
            "iata": row["iata"],
            "icao": row["icao"] or None,
            "name": row["name"],
            "carrier_type": row["carrier_type"],
        }
        for row in read_seed_csv(seeds_dir / "carriers.csv")
    ]


def route_rows(basket: BasketConfig) -> list[dict[str, Any]]:
    """``route`` table rows derived from the basket — the basket's only definition."""
    return [
        {
            "origin_iata": route.origin,
            "dest_iata": route.dest,
            "code": route.code,
            "dgca_pax_share": route.dgca_pax_share,
            "basket_version": basket.basket_version,
            "active_from": route.active_from,
            "active_to": route.active_to,
        }
        for route in basket.routes
    ]


def load_airport_coords(seeds_dir: Path) -> dict[str, tuple[float, float]]:
    """IATA -> (lat, lon) from the airports seed, for distance computations."""
    return {
        row["iata"]: (float(row["lat"]), float(row["lon"]))
        for row in read_seed_csv(seeds_dir / "airports.csv")
    }


def seed_reference(session: Session, seeds_dir: Path, basket: BasketConfig) -> ReferenceCounts:
    """Load airports, carriers and routes. Idempotent; commits nothing itself."""
    session.execute(pg_insert(Airport).values(airport_rows(seeds_dir)).on_conflict_do_nothing())
    session.execute(pg_insert(Carrier).values(carrier_rows(seeds_dir)).on_conflict_do_nothing())
    session.execute(pg_insert(Route).values(route_rows(basket)).on_conflict_do_nothing())
    return ReferenceCounts(
        airports=session.scalar(select(func.count()).select_from(Airport)) or 0,
        carriers=session.scalar(select(func.count()).select_from(Carrier)) or 0,
        routes=session.scalar(select(func.count()).select_from(Route)) or 0,
    )


__all__ = [
    "ReferenceCounts",
    "airport_rows",
    "carrier_rows",
    "load_airport_coords",
    "read_seed_csv",
    "route_rows",
    "seed_reference",
]
