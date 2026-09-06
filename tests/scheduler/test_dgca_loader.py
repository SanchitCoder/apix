"""The DGCA traffic loader: complete weight vectors or nothing, comments preserved.

All passenger counts in these tests are FAKE, chosen to exercise the parsing and
matching logic. No real DGCA figure appears anywhere in the test suite; the real
release is loaded by a human following docs/data-sources.md.
"""

from __future__ import annotations

import shutil
from decimal import Decimal

import pytest

from apix_core.config import BasketConfig, load_basket, load_config
from apix_core.seeding import read_seed_csv
from apix_scheduler.dgca_loader import (
    DgcaLoadError,
    compute_shares,
    load_dgca_release,
    read_extract,
    rewrite_basket_yaml,
)

TOTAL_PAX = 10_000_000  # fake denominator

# Reverse of the loader's CITY_ALIASES, so the fixture extract uses DGCA-style
# spellings and the alias mapping is genuinely exercised.
_DGCA_SPELLING = {
    "New Delhi": "DELHI",
    "Bengaluru": "BANGALORE",
    "Vasco da Gama": "GOA",
    "Kochi": "COCHIN",
}


@pytest.fixture
def env(tmp_path, repo_root):
    """A throwaway config/ + db/seeds/ pair copied from the real files."""
    config_dir = tmp_path / "config"
    seeds_dir = tmp_path / "db" / "seeds"
    config_dir.mkdir()
    seeds_dir.mkdir(parents=True)
    shutil.copy(repo_root / "config" / "basket.yaml", config_dir / "basket.yaml")
    shutil.copy(repo_root / "db" / "seeds" / "airports.csv", seeds_dir / "airports.csv")
    return config_dir, seeds_dir


def _write_extract(path, repo_root, *, skip_codes=frozenset()):
    """A complete fake extract covering every basket route, in DGCA spellings."""
    basket = load_basket(repo_root / "config")
    seeds = repo_root / "db" / "seeds"
    city = {r["iata"]: r["city"] for r in read_seed_csv(seeds / "airports.csv")}
    lines = [
        "# FAKE fixture data for tests — not a DGCA release",
        "origin_city,dest_city,passengers",
    ]
    for i, route in enumerate(basket.routes):
        if route.code in skip_codes:
            continue
        origin = _DGCA_SPELLING.get(city[route.origin], city[route.origin].upper())
        dest = _DGCA_SPELLING.get(city[route.dest], city[route.dest].upper())
        lines.append(f"{origin},{dest},{100_000 + i * 1_000}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return basket


def test_full_load_populates_every_route_and_preserves_comments(env, repo_root, tmp_path) -> None:
    config_dir, seeds_dir = env
    extract = tmp_path / "extract.csv"
    _write_extract(extract, repo_root)

    shares = load_dgca_release(extract, "2026-07", TOTAL_PAX, config_dir, seeds_dir)
    assert len(shares) == 50

    rewritten = load_basket(config_dir)
    assert rewritten.weights_are_populated
    assert sum(r.dgca_pax_share for r in rewritten.routes) <= 1
    text = (config_dir / "basket.yaml").read_text(encoding="utf-8")
    assert "Routes are directional" in text, "the file's own commentary must survive"
    assert "DGCA 2026-07 monthly traffic release" in text


def test_dry_run_writes_nothing(env, repo_root, tmp_path) -> None:
    config_dir, seeds_dir = env
    extract = tmp_path / "extract.csv"
    _write_extract(extract, repo_root)
    before = (config_dir / "basket.yaml").read_bytes()

    shares = load_dgca_release(extract, "2026-07", TOTAL_PAX, config_dir, seeds_dir, dry_run=True)
    assert len(shares) == 50
    assert (config_dir / "basket.yaml").read_bytes() == before


def test_a_missing_route_aborts_the_whole_load(env, repo_root, tmp_path) -> None:
    """A partial weight vector is never written — same rule as BasketConfig."""
    config_dir, seeds_dir = env
    extract = tmp_path / "extract.csv"
    _write_extract(extract, repo_root, skip_codes={"BOM-DEL"})
    before = (config_dir / "basket.yaml").read_bytes()

    with pytest.raises(DgcaLoadError, match="BOM-DEL"):
        load_dgca_release(extract, "2026-07", TOTAL_PAX, config_dir, seeds_dir)
    assert (config_dir / "basket.yaml").read_bytes() == before


def test_an_implausible_denominator_is_refused(env, repo_root, tmp_path) -> None:
    config_dir, seeds_dir = env
    extract = tmp_path / "extract.csv"
    _write_extract(extract, repo_root)
    with pytest.raises(DgcaLoadError, match="more than 1"):
        load_dgca_release(extract, "2026-07", 1_000_000, config_dir, seeds_dir)


def test_month_must_be_well_formed(env, repo_root, tmp_path) -> None:
    config_dir, seeds_dir = env
    extract = tmp_path / "extract.csv"
    _write_extract(extract, repo_root)
    with pytest.raises(DgcaLoadError, match="2026-07"):
        load_dgca_release(extract, "July 2026", TOTAL_PAX, config_dir, seeds_dir)


def test_extract_with_wrong_columns_is_rejected(tmp_path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("city_a,city_b,pax\nDELHI,MUMBAI,1\n", encoding="utf-8")
    with pytest.raises(DgcaLoadError, match="expected columns"):
        read_extract(bad)


def test_extract_tolerates_comma_grouped_numbers(tmp_path) -> None:
    path = tmp_path / "extract.csv"
    path.write_text(
        'origin_city,dest_city,passengers\nDELHI,MUMBAI,"1,234,567"\n', encoding="utf-8"
    )
    assert read_extract(path) == {("NEW DELHI", "MUMBAI"): 1_234_567}


def test_duplicate_pairs_are_rejected(tmp_path) -> None:
    path = tmp_path / "extract.csv"
    path.write_text(
        "origin_city,dest_city,passengers\nDELHI,MUMBAI,10\nDelhi,Mumbai,20\n",
        encoding="utf-8",
    )
    with pytest.raises(DgcaLoadError, match="duplicate"):
        read_extract(path)


def test_shares_are_exact_quotients(repo_root) -> None:
    basket = load_basket(repo_root / "config")
    seeds = repo_root / "db" / "seeds"
    city = {r["iata"]: r["city"] for r in read_seed_csv(seeds / "airports.csv")}
    pairs = {
        (city[route.origin].upper(), city[route.dest].upper()): 20_000 for route in basket.routes
    }
    shares = compute_shares(basket, city, pairs, 2_000_000)
    assert all(s == Decimal("0.01000000") for s in shares.values())


def test_rewrite_refuses_unknown_routes(repo_root) -> None:
    basket_path = repo_root / "config" / "basket.yaml"
    with pytest.raises(DgcaLoadError, match="XXX-YYY"):
        rewrite_basket_yaml(basket_path, {"XXX-YYY": Decimal("0.1")}, "2026-07")


def test_rewritten_yaml_revalidates_against_the_schema(env, repo_root, tmp_path) -> None:
    config_dir, seeds_dir = env
    extract = tmp_path / "extract.csv"
    _write_extract(extract, repo_root)
    load_dgca_release(extract, "2026-07", TOTAL_PAX, config_dir, seeds_dir)
    validated = load_config(config_dir / "basket.yaml", BasketConfig)
    assert validated.weights_are_populated
