"""Load DGCA monthly domestic traffic into ``config/basket.yaml``'s route weights.

The DGCA monthly Domestic Traffic Report is a formatted workbook published for human
readers; its city-pair table is extracted by hand to a small normalised CSV (the exact
procedure, and where the file lives, is documented in ``docs/data-sources.md``):

    origin_city,dest_city,passengers
    DELHI,MUMBAI,412345
    MUMBAI,DELHI,401234
    ...

with one directional row per city-pair and ``passengers`` the passengers flown on that
direction in the month. This loader maps the city names onto the basket's airports,
computes each route's share of total domestic passengers, and rewrites
``dgca_pax_share`` for **every** basket route — BasketConfig rejects a partially
populated weight vector, and so does this loader. If any basket route is missing from
the extract, nothing is written and the missing pairs are listed.

No fare data, no estimation, no interpolation: the shares written are exactly
``passengers / total_domestic_passengers`` from one named monthly release.
"""

from __future__ import annotations

import argparse
import csv
import re
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from apix_core.config import BasketConfig, ConfigError, find_config_dir, load_basket, load_config
from apix_core.seeding import read_seed_csv

if TYPE_CHECKING:
    from collections.abc import Mapping

log = structlog.get_logger(__name__)

# DGCA spellings -> the city names used in db/seeds/airports.csv (upper-cased).
# Name normalisation only; never numbers.
CITY_ALIASES: dict[str, str] = {
    "DELHI": "NEW DELHI",
    "BANGALORE": "BENGALURU",
    "BOMBAY": "MUMBAI",
    "MADRAS": "CHENNAI",
    "CALCUTTA": "KOLKATA",
    "COCHIN": "KOCHI",
    "GOA": "VASCO DA GAMA",  # basket flies GOI (Dabolim); DGCA reports the city as Goa
    "TRIVANDRUM": "THIRUVANANTHAPURAM",
    "PONDICHERRY": "PUDUCHERRY",
}

_SHARE_PLACES = Decimal("0.00000001")  # route.dgca_pax_share is Numeric(9, 8)
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_CODE_LINE_RE = re.compile(r'^\s*- code: "([A-Z]{3}-[A-Z]{3})"')
_SHARE_LINE_RE = re.compile(r"^(\s*)dgca_pax_share:\s*(null|[0-9.]+)\b.*$")


class DgcaLoadError(RuntimeError):
    """The extract cannot populate the basket completely and correctly."""


def _canon(city: str) -> str:
    name = " ".join(city.upper().split())
    return CITY_ALIASES.get(name, name)


def read_extract(path: Path) -> dict[tuple[str, str], int]:
    """Directional city-pair passenger counts from the normalised CSV extract."""
    with path.open(encoding="utf-8", newline="") as fh:
        lines = [line for line in fh if not line.startswith("#")]
    reader = csv.DictReader(lines)
    required = {"origin_city", "dest_city", "passengers"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise DgcaLoadError(
            f"{path}: expected columns origin_city,dest_city,passengers (got {reader.fieldnames})"
        )
    pairs: dict[tuple[str, str], int] = {}
    for row in reader:
        key = (_canon(row["origin_city"]), _canon(row["dest_city"]))
        if key in pairs:
            raise DgcaLoadError(f"{path}: duplicate city pair {key[0]} -> {key[1]}")
        try:
            passengers = int(row["passengers"].replace(",", "").strip())
        except ValueError as exc:
            raise DgcaLoadError(f"{path}: bad passenger count in row {row}") from exc
        if passengers < 0:
            raise DgcaLoadError(f"{path}: negative passenger count in row {row}")
        pairs[key] = passengers
    if not pairs:
        raise DgcaLoadError(f"{path}: no data rows")
    return pairs


def compute_shares(
    basket: BasketConfig,
    airport_city: Mapping[str, str],
    pairs: Mapping[tuple[str, str], int],
    total_domestic_pax: int,
) -> dict[str, Decimal]:
    """dgca_pax_share per basket route code. All routes or nothing."""
    if total_domestic_pax <= 0:
        raise DgcaLoadError("total_domestic_pax must be positive")
    shares: dict[str, Decimal] = {}
    missing: list[str] = []
    for route in basket.routes:
        try:
            key = (_canon(airport_city[route.origin]), _canon(airport_city[route.dest]))
        except KeyError as exc:
            raise DgcaLoadError(f"route {route.code}: airport {exc} not in airports seed") from exc
        if key not in pairs:
            missing.append(f"{route.code} ({key[0]} -> {key[1]})")
            continue
        share = (Decimal(pairs[key]) / Decimal(total_domestic_pax)).quantize(
            _SHARE_PLACES, rounding=ROUND_HALF_EVEN
        )
        shares[route.code] = share
    if missing:
        raise DgcaLoadError(
            "the extract is missing these basket routes — an incomplete weight vector "
            "is never written:\n  " + "\n  ".join(missing)
        )
    if sum(shares.values()) > 1:
        raise DgcaLoadError("route shares sum to more than 1; check total_domestic_pax")
    return shares


def rewrite_basket_yaml(basket_path: Path, shares: Mapping[str, Decimal], month: str) -> str:
    """Return ``basket.yaml`` text with every route's share replaced in place.

    Text-level editing keeps the file's comments and layout intact; the result is
    re-validated against BasketConfig before anything is written to disk.
    """
    current_code: str | None = None
    replaced: set[str] = set()
    out_lines: list[str] = []
    for line in basket_path.read_text(encoding="utf-8").splitlines():
        code_match = _CODE_LINE_RE.match(line)
        if code_match:
            current_code = code_match.group(1)
        share_match = _SHARE_LINE_RE.match(line)
        if share_match and current_code is not None and current_code in shares:
            indent = share_match.group(1)
            share = shares[current_code]
            line = f"{indent}dgca_pax_share: {share}  # DGCA {month} monthly traffic release"
            replaced.add(current_code)
        out_lines.append(line)
    unreplaced = sorted(set(shares) - replaced)
    if unreplaced:
        raise DgcaLoadError(f"could not locate dgca_pax_share lines for routes: {unreplaced}")
    return "\n".join(out_lines) + "\n"


def load_dgca_release(
    extract_path: Path,
    month: str,
    total_domestic_pax: int,
    config_dir: Path,
    seeds_dir: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Decimal]:
    """Populate basket.yaml from one month's extract. Returns the shares written."""
    if not _MONTH_RE.match(month):
        raise DgcaLoadError(f"month {month!r} must look like 2026-07")
    basket_path = config_dir / "basket.yaml"
    basket = load_basket(config_dir)
    airport_city = {row["iata"]: row["city"] for row in read_seed_csv(seeds_dir / "airports.csv")}
    pairs = read_extract(extract_path)
    shares = compute_shares(basket, airport_city, pairs, total_domestic_pax)
    new_text = rewrite_basket_yaml(basket_path, shares, month)

    # Validate the rewritten file before it replaces the real one.
    trial = basket_path.with_suffix(".yaml.dgca-trial")
    trial.write_text(new_text, encoding="utf-8")
    try:
        validated = load_config(trial, BasketConfig)
        if not validated.weights_are_populated:
            raise DgcaLoadError("rewrite left some routes unweighted — refusing to write")
    except ConfigError as exc:
        raise DgcaLoadError(f"rewritten basket.yaml fails validation: {exc}") from exc
    finally:
        trial.unlink(missing_ok=True)

    if dry_run:
        log.info("dgca_load_dry_run", month=month, routes=len(shares))
    else:
        basket_path.write_text(new_text, encoding="utf-8")
        log.info(
            "dgca_load_written",
            month=month,
            routes=len(shares),
            basket_share_sum=str(sum(shares.values())),
            extract=str(extract_path),
        )
    return shares


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Populate config/basket.yaml dgca_pax_share from a DGCA monthly extract."
    )
    parser.add_argument(
        "extract", type=Path, help="normalised city-pair CSV (see docs/data-sources.md)"
    )
    parser.add_argument("--month", required=True, help="release month, e.g. 2026-07")
    parser.add_argument(
        "--total-domestic-pax",
        required=True,
        type=int,
        help="total domestic passengers carried that month, from the same release",
    )
    parser.add_argument("--dry-run", action="store_true", help="validate and report; write nothing")
    args = parser.parse_args(argv)

    config_dir = find_config_dir()
    seeds_dir = config_dir.parent / "db" / "seeds"
    load_dgca_release(
        args.extract,
        args.month,
        args.total_domestic_pax,
        config_dir,
        seeds_dir,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via unit tests on the functions
    raise SystemExit(main())
