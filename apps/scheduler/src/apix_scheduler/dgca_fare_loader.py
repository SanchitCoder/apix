"""Load a DGCA (or other cited official benchmark) average-fare extract into
``dgca_fare_reference``.

Distinct from ``apix_scheduler.dgca_loader``, which loads DGCA passenger *shares* into
``config/basket.yaml``: this loader is for average *fares*, and writes database rows,
not a config file. As documented in ``docs/data-sources.md``, DGCA's Monthly Domestic
Traffic release — the only DGCA feed this repository has actually inspected — publishes
traffic and capacity, not average fares; this loader is ready for whatever official
fare benchmark is eventually cited, and takes a small, human-produced, cited CSV
extract exactly like ``dgca_loader`` does, for the same reason: no automated collection
of any such source is reviewed or enabled (``config/sources.yaml``).

    # <benchmark name> average fare extract for July 2026.
    # Downloaded 2026-09-10 from <exact URL>. Extracted by <name> on <date>.
    route_code,period,avg_fare
    DEL-BOM,2026-07,5432.10
    BOM-DEL,2026-07,5310.00
    ...

Every basket route in the extract must exist in the ``route`` table; a row for a
route this deployment does not know about aborts the whole load — nothing partial is
written. Insertion is append-only: re-loading the same period is a second row, not an
overwrite (the same discipline as ``fare_quote``/``index_value``), so a correction is
visible as a correction, not silently substituted.
"""

from __future__ import annotations

import argparse
import csv
import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apix_core.models import DgcaFareReference, Route
from apix_core.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Mapping

log = structlog.get_logger(__name__)

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_AVG_FARE_PLACES = Decimal("0.01")


class DgcaFareLoadError(RuntimeError):
    """The extract cannot be loaded completely and correctly."""


@dataclass(frozen=True)
class FareRow:
    route_code: str
    period: date
    avg_fare: Decimal


def read_extract(path: Path) -> list[FareRow]:
    """Parse the normalised ``route_code,period,avg_fare`` CSV extract."""
    with path.open(encoding="utf-8", newline="") as fh:
        lines = [line for line in fh if not line.startswith("#")]
    reader = csv.DictReader(lines)
    required = {"route_code", "period", "avg_fare"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise DgcaFareLoadError(
            f"{path}: expected columns route_code,period,avg_fare (got {reader.fieldnames})"
        )
    rows: list[FareRow] = []
    seen: set[tuple[str, str]] = set()
    for row in reader:
        route_code = row["route_code"].strip().upper()
        period_str = row["period"].strip()
        if not _PERIOD_RE.match(period_str):
            raise DgcaFareLoadError(f"{path}: bad period {period_str!r} for route {route_code}")
        key = (route_code, period_str)
        if key in seen:
            raise DgcaFareLoadError(f"{path}: duplicate row for {route_code} {period_str}")
        seen.add(key)
        try:
            avg_fare = Decimal(row["avg_fare"].replace(",", "").strip()).quantize(
                _AVG_FARE_PLACES, rounding=ROUND_HALF_EVEN
            )
        except InvalidOperation as exc:
            raise DgcaFareLoadError(f"{path}: bad avg_fare in row {row}") from exc
        if avg_fare <= 0:
            raise DgcaFareLoadError(f"{path}: avg_fare must be positive in row {row}")
        year_str, month_str = period_str.split("-")
        rows.append(FareRow(route_code, date(int(year_str), int(month_str), 1), avg_fare))
    if not rows:
        raise DgcaFareLoadError(f"{path}: no data rows")
    return rows


def resolve_route_ids(session: Session, route_codes: set[str]) -> Mapping[str, uuid.UUID]:
    """Route id for every code, or raise listing whatever is missing — nothing
    partial is written for an extract naming a route this deployment does not know.
    """
    found = dict(
        session.execute(select(Route.code, Route.id).where(Route.code.in_(route_codes)))
        .tuples()
        .all()
    )
    missing = sorted(route_codes - set(found))
    if missing:
        raise DgcaFareLoadError(f"routes not found in the route table: {missing}")
    return found


def load_dgca_fares(
    session: Session,
    extract_path: Path,
    source_note: str,
    *,
    dry_run: bool = False,
) -> list[FareRow]:
    """Load ``extract_path`` into ``dgca_fare_reference``. Returns the rows loaded."""
    rows = read_extract(extract_path)
    route_ids = resolve_route_ids(session, {r.route_code for r in rows})

    if dry_run:
        log.info("dgca_fare_load_dry_run", extract=str(extract_path), rows=len(rows))
        return rows

    session.add_all(
        DgcaFareReference(
            id=uuid.uuid4(),
            route_id=route_ids[row.route_code],
            period=row.period,
            avg_fare=row.avg_fare,
            source_note=source_note,
        )
        for row in rows
    )
    session.commit()
    log.info(
        "dgca_fare_load_written",
        extract=str(extract_path),
        rows=len(rows),
        routes=sorted({r.route_code for r in rows}),
    )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Load a DGCA/cited-benchmark average-fare extract into dgca_fare_reference."
    )
    parser.add_argument(
        "extract",
        type=Path,
        help="normalised route_code,period,avg_fare CSV (see module docstring)",
    )
    parser.add_argument(
        "--source-note",
        required=True,
        help="citation for this release, e.g. 'DGCA Monthly Domestic Traffic Report, "
        "July 2026, <url>, extracted 2026-09-10'",
    )
    parser.add_argument("--dry-run", action="store_true", help="validate and report; write nothing")
    parser.add_argument(
        "--database-url", default=None, help="target database (default: APIX_DATABASE_SYNC_URL)"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    database_url = args.database_url or settings.database_sync_url
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            load_dgca_fares(session, args.extract, args.source_note, dry_run=args.dry_run)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via unit tests on the functions
    raise SystemExit(main())
