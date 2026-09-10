"""Load an ATF (aviation turbine fuel) price extract into ``atf_price``.

No automated ATF price collection is reviewed or enabled (``config/sources.yaml``
carries no such source yet — see ``docs/data-sources.md``), so this loader takes a
small, human-produced, cited CSV extract, the same "loader ready, data NOT loaded"
shape as ``apix_scheduler.dgca_loader``:

    # IOCL ATF price notification, effective 2026-09-01.
    # Downloaded 2026-09-10 from <exact URL>. Extracted by <name> on <date>.
    price_date,city,price_per_kl
    2026-09-01,Delhi,98765.43
    2026-09-01,Mumbai,97654.32
    ...

Insertion is append-only: a later, corrected notification is a new row, never an
overwrite.
"""

from __future__ import annotations

import argparse
import csv
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apix_core.models import AtfPrice
from apix_core.settings import get_settings

log = structlog.get_logger(__name__)

_PRICE_PLACES = Decimal("0.01")


class AtfLoadError(RuntimeError):
    """The extract cannot be loaded completely and correctly."""


@dataclass(frozen=True)
class AtfPriceRow:
    price_date: date
    city: str
    price_per_kl: Decimal


def read_extract(path: Path) -> list[AtfPriceRow]:
    with path.open(encoding="utf-8", newline="") as fh:
        lines = [line for line in fh if not line.startswith("#")]
    reader = csv.DictReader(lines)
    required = {"price_date", "city", "price_per_kl"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise AtfLoadError(
            f"{path}: expected columns price_date,city,price_per_kl (got {reader.fieldnames})"
        )
    rows: list[AtfPriceRow] = []
    for row in reader:
        try:
            price_date = date.fromisoformat(row["price_date"].strip())
        except ValueError as exc:
            raise AtfLoadError(f"{path}: bad price_date in row {row}") from exc
        city = row["city"].strip()
        if not city:
            raise AtfLoadError(f"{path}: empty city in row {row}")
        try:
            price = Decimal(row["price_per_kl"].replace(",", "").strip()).quantize(
                _PRICE_PLACES, rounding=ROUND_HALF_EVEN
            )
        except InvalidOperation as exc:
            raise AtfLoadError(f"{path}: bad price_per_kl in row {row}") from exc
        if price <= 0:
            raise AtfLoadError(f"{path}: price_per_kl must be positive in row {row}")
        rows.append(AtfPriceRow(price_date, city, price))
    if not rows:
        raise AtfLoadError(f"{path}: no data rows")
    return rows


def load_atf_prices(
    session: Session, extract_path: Path, source_note: str, *, dry_run: bool = False
) -> list[AtfPriceRow]:
    rows = read_extract(extract_path)
    if dry_run:
        log.info("atf_load_dry_run", extract=str(extract_path), rows=len(rows))
        return rows
    session.add_all(
        AtfPrice(
            id=uuid.uuid4(),
            price_date=row.price_date,
            city=row.city,
            price_per_kl=row.price_per_kl,
            source_note=source_note,
        )
        for row in rows
    )
    session.commit()
    log.info("atf_load_written", extract=str(extract_path), rows=len(rows))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load an ATF price extract into atf_price.")
    parser.add_argument("extract", type=Path, help="normalised price_date,city,price_per_kl CSV")
    parser.add_argument(
        "--source-note",
        required=True,
        help="citation, e.g. 'IOCL ATF price notification, effective 2026-09-01, <url>'",
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
            load_atf_prices(session, args.extract, args.source_note, dry_run=args.dry_run)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via unit tests on the functions
    raise SystemExit(main())
