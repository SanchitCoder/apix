"""The reference seed files and their loaders: real data, coherent with the basket."""

from __future__ import annotations

import pytest

from apix_core.config import load_basket
from apix_core.models.enums import CarrierType
from apix_core.seeding import (
    airport_rows,
    carrier_rows,
    load_airport_coords,
    read_seed_csv,
    route_rows,
)


@pytest.fixture(scope="module")
def seeds_dir(repo_root):
    return repo_root / "db" / "seeds"


def test_comment_headers_are_skipped_but_data_is_read(seeds_dir) -> None:
    rows = read_seed_csv(seeds_dir / "airports.csv")
    assert len(rows) > 100  # all Indian airports with scheduled service, not just 14
    assert all(not r["iata"].startswith("#") for r in rows)


def test_missing_data_rows_are_an_error(tmp_path) -> None:
    empty = tmp_path / "airports.csv"
    empty.write_text("# only a comment\niata,name\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no data rows"):
        read_seed_csv(empty)


def test_airport_rows_fit_the_model_contract(seeds_dir) -> None:
    rows = airport_rows(seeds_dir)
    iatas = [r["iata"] for r in rows]
    assert len(iatas) == len(set(iatas))
    for row in rows:
        assert len(row["iata"]) == 3
        assert row["icao"] is None or len(row["icao"]) == 4
        assert row["name"] and len(row["name"]) <= 128
        assert row["city"] and len(row["city"]) <= 64
        assert -90 <= row["lat"] <= 90
        assert -180 <= row["lon"] <= 180


def test_carrier_rows_use_the_controlled_vocabulary(seeds_dir) -> None:
    rows = carrier_rows(seeds_dir)
    assert {r["iata"] for r in rows} >= {"AI", "6E", "IX", "SG", "QP"}
    for row in rows:
        assert len(row["iata"]) == 2
        CarrierType(row["carrier_type"])  # raises if not in the enum


def test_every_basket_airport_is_in_the_seed(seeds_dir, config_dir) -> None:
    """Referential integrity of the shipped files: routes must be insertable."""
    basket = load_basket(config_dir)
    seeded = {r["iata"] for r in airport_rows(seeds_dir)}
    needed = {r.origin for r in basket.routes} | {r.dest for r in basket.routes}
    assert needed <= seeded, f"basket airports missing from seed: {sorted(needed - seeded)}"


def test_route_rows_come_from_the_basket_alone(config_dir) -> None:
    basket = load_basket(config_dir)
    rows = route_rows(basket)
    assert len(rows) == len(basket.routes)
    for row in rows:
        assert row["code"] == f"{row['origin_iata']}-{row['dest_iata']}"
        assert row["basket_version"] == basket.basket_version
        # Phase 2 loads real DGCA weights; until then a null share is the record.
        assert row["dgca_pax_share"] is None or 0 <= row["dgca_pax_share"] <= 1


def test_airport_coords_cover_the_seed(seeds_dir) -> None:
    coords = load_airport_coords(seeds_dir)
    assert coords["DEL"] == pytest.approx((28.5562, 77.1000), abs=0.01)
    assert len(coords) == len(airport_rows(seeds_dir))
