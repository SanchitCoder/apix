"""Load a CPI air-fare item index extract into ``cpi_airfare_index``.

No automated collection of MoSPI's CPI release is reviewed or enabled (see
``docs/data-sources.md``), so this loader takes a small, human-produced, cited CSV
extract of the published air-fare item index, the same "loader ready, data NOT
loaded" shape as ``apix_scheduler.dgca_loader``:

    # MoSPI CPI (Rural+Urban), Transport and communication -> Air fare item index.
    # Downloaded 2026-09-10 from <exact URL>. Extracted by <name> on <date>.
    period,value,base_year,release_date
    2026-07,142.3,2011-12,2026-08-12
    ...

Insertion is append-only: a later MoSPI revision of a period is a new row with a
later ``release_date``, never an overwrite of the earlier vintage.
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

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apix_core.models import CpiAirfareIndex
from apix_core.settings import get_settings

log = structlog.get_logger(__name__)

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_VALUE_PLACES = Decimal("0.000001")


class CpiLoadError(RuntimeError):
    """The extract cannot be loaded completely and correctly."""


@dataclass(frozen=True)
class CpiRow:
    period: date
    value: Decimal
    base_year: str
    release_date: date


def read_extract(path: Path) -> list[CpiRow]:
    with path.open(encoding="utf-8", newline="") as fh:
        lines = [line for line in fh if not line.startswith("#")]
    reader = csv.DictReader(lines)
    required = {"period", "value", "base_year", "release_date"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise CpiLoadError(
            f"{path}: expected columns period,value,base_year,release_date "
            f"(got {reader.fieldnames})"
        )
    rows: list[CpiRow] = []
    for row in reader:
        period_str = row["period"].strip()
        if not _PERIOD_RE.match(period_str):
            raise CpiLoadError(f"{path}: bad period {period_str!r} in row {row}")
        year_str, month_str = period_str.split("-")
        try:
            value = Decimal(row["value"].strip()).quantize(_VALUE_PLACES, rounding=ROUND_HALF_EVEN)
        except InvalidOperation as exc:
            raise CpiLoadError(f"{path}: bad value in row {row}") from exc
        if value <= 0:
            raise CpiLoadError(f"{path}: value must be positive in row {row}")
        base_year = row["base_year"].strip()
        if not base_year:
            raise CpiLoadError(f"{path}: empty base_year in row {row}")
        try:
            release_date = date.fromisoformat(row["release_date"].strip())
        except ValueError as exc:
            raise CpiLoadError(f"{path}: bad release_date in row {row}") from exc
        rows.append(CpiRow(date(int(year_str), int(month_str), 1), value, base_year, release_date))
    if not rows:
        raise CpiLoadError(f"{path}: no data rows")
    return rows


def load_cpi_airfare_index(
    session: Session, extract_path: Path, source_note: str, *, dry_run: bool = False
) -> list[CpiRow]:
    rows = read_extract(extract_path)
    if dry_run:
        log.info("cpi_load_dry_run", extract=str(extract_path), rows=len(rows))
        return rows
    session.add_all(
        CpiAirfareIndex(
            id=uuid.uuid4(),
            period=row.period,
            value=row.value,
            base_year=row.base_year,
            release_date=row.release_date,
            source_note=source_note,
        )
        for row in rows
    )
    session.commit()
    log.info("cpi_load_written", extract=str(extract_path), rows=len(rows))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Load a CPI air-fare item index extract into cpi_airfare_index."
    )
    parser.add_argument(
        "extract", type=Path, help="normalised period,value,base_year,release_date CSV"
    )
    parser.add_argument(
        "--source-note",
        required=True,
        help="citation, e.g. 'MoSPI CPI release, July 2026, <url>, extracted 2026-09-10'",
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
            load_cpi_airfare_index(session, args.extract, args.source_note, dry_run=args.dry_run)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via unit tests on the functions
    raise SystemExit(main())
