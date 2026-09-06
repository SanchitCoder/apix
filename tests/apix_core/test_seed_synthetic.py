"""The synthetic seeder: the production guard and the row-shaping helpers.

The guard has no override flag on purpose; these tests are what make that a promise.
Database round-trips live in tests/integration/test_seed_synthetic_db.py.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta, timezone

import pytest

from apix_core.config import load_basket, load_synthetic
from apix_core.seeding import load_airport_coords
from apix_core.settings import Environment
from apix_core.testing.seed import (
    SyntheticSeedRefusedError,
    _collection_run_rows,
    _quote_records,
    _source_rows,
    _write_ground_truth,
    refuse_unsafe_database,
)
from apix_core.testing.synthetic import generate

LOCAL_URL = "postgresql+psycopg2://apix:apix@localhost:5432/apix"


# ------------------------------------------------------------------ the guard ----


def test_local_database_in_local_env_is_allowed() -> None:
    refuse_unsafe_database(LOCAL_URL, Environment.LOCAL)
    refuse_unsafe_database(LOCAL_URL, Environment.CI)


@pytest.mark.parametrize("env", [Environment.STAGING, Environment.PRODUCTION])
def test_deployed_environments_are_refused_regardless_of_url(env) -> None:
    with pytest.raises(SyntheticSeedRefusedError, match="never seeded outside local/ci"):
        refuse_unsafe_database(LOCAL_URL, env)


def test_remote_hosts_are_refused() -> None:
    with pytest.raises(SyntheticSeedRefusedError, match="not a local development host"):
        refuse_unsafe_database(
            "postgresql+psycopg2://apix:x@db.apix.example.net:5432/apix", Environment.LOCAL
        )


def test_a_production_looking_name_is_refused_even_on_localhost() -> None:
    """An SSH tunnel makes production answer on localhost; the name still gives it away."""
    with pytest.raises(SyntheticSeedRefusedError, match="looks like production"):
        refuse_unsafe_database(
            "postgresql+psycopg2://apix:x@localhost:5432/apix_prod", Environment.LOCAL
        )


def test_compose_internal_hostnames_are_allowed() -> None:
    refuse_unsafe_database("postgresql+psycopg2://apix:x@postgres:5432/apix", Environment.LOCAL)


# ------------------------------------------------------------ the row shaping ----


@pytest.fixture(scope="module")
def cfg(repo_root):
    return load_synthetic(repo_root / "config")


@pytest.fixture(scope="module")
def small_dataset(cfg, repo_root):
    basket = load_basket(repo_root / "config")
    coords = load_airport_coords(repo_root / "db" / "seeds")
    return generate(cfg, basket, coords, date(2026, 6, 7), 3)


@pytest.fixture(scope="module")
def records(cfg, small_dataset, repo_root):
    basket = load_basket(repo_root / "config")
    route_ids = {r.code: uuid.uuid4() for r in basket.routes}
    return _quote_records(cfg, small_dataset, route_ids)


def test_every_record_is_tagged_synthetic_on_all_three_dimensions(records) -> None:
    for record in records:
        assert record["collection_method"] == "SYNTHETIC"
        assert record["legal_basis"] == "SYNTHETIC"
    # source_type is on the source row, not the quote:
    # covered by test_synthetic_sources below.


def test_synthetic_sources_are_labelled_disabled_and_unresolvable(cfg) -> None:
    rows = _source_rows(cfg)
    for row in rows:
        assert row["source_type"] == "SYNTHETIC"
        assert row["enabled"] is False
        assert str(row["domain"]).endswith(".invalid")  # RFC 2606: can never resolve


def test_records_satisfy_the_fare_quote_contract(records, small_dataset) -> None:
    assert len(records) == len(small_dataset.quotes)
    hashes = set()
    for record in records:
        assert len(record["content_hash"]) == 64
        hashes.add((record["content_hash"], record["collected_at"]))
        assert record["total_fare"] >= 0
        assert record["travel_date"] >= record["query_date"]
        assert 0 <= record["advance_days"] <= 365
        assert record["currency"] == "INR"
        assert record["collected_at"].tzinfo is not None
        assert record["dep_datetime_local"].tzinfo is None  # local time is naive by design
    # The dedup index (content_hash, collected_at) must not reject legitimate rows.
    assert len(hashes) == len(records)


def test_collected_at_is_stable_per_collection_day(cfg, records) -> None:
    """Provenance: quotes of one run carry that run's timestamp, in IST."""
    by_day = {(r["run_id"], r["collected_at"]) for r in records}
    assert len({run_id for run_id, _ in by_day}) == len(by_day)
    sample = records[0]["collected_at"]
    ist = sample.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert ist.hour == cfg.collection.collection_hour_ist


def test_collection_runs_account_for_every_quote(cfg, small_dataset, records) -> None:
    """Principle 2: run rows carry counts, so nothing collected goes unaccounted."""
    runs = _collection_run_rows(cfg, small_dataset.quotes)
    assert sum(r["quotes_collected"] for r in runs) == len(records)
    assert {r["status"] for r in runs} == {"SUCCEEDED"}
    run_ids = {r["id"] for r in runs}
    assert {r["run_id"] for r in records} <= run_ids


def test_ground_truth_file_is_deterministic_and_labelled(cfg, small_dataset, tmp_path) -> None:
    out = tmp_path / "truth.json"
    _write_ground_truth(out, cfg, small_dataset, quote_count=len(small_dataset.quotes))
    first = out.read_bytes()
    payload = json.loads(first)
    assert "SYNTHETIC" in payload["warning"]
    assert payload["seed"] == cfg.seed
    assert payload["anomaly_count"] == len(small_dataset.anomalies)
    assert (tmp_path / "sold_out_cells.csv").exists()

    _write_ground_truth(out, cfg, small_dataset, quote_count=len(small_dataset.quotes))
    assert out.read_bytes() == first, "ground truth must be byte-identical on re-run"
