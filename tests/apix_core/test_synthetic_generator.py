"""The synthetic generator must actually have the statistical properties it claims.

These tests are the contract for `make seed-synthetic`: determinism, the booking
curve, weekly and festival seasonality, distance-driven price levels, the Indian fare
component structure, sell-out missingness, and a ground-truth file that matches the
damage actually done to the quotes.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import date, timedelta

import pandas as pd
import pytest

from apix_core.config import load_basket, load_synthetic
from apix_core.config.synthetic import AnomalyKind
from apix_core.seeding import load_airport_coords
from apix_core.testing.synthetic import (
    SYNTHETIC_UUID_NAMESPACE,
    generate,
    haversine_km,
    lead_time_multipliers,
)

START = date(2026, 6, 7)
DAYS = 30


@pytest.fixture(scope="module")
def cfg(repo_root):
    return load_synthetic(repo_root / "config")


@pytest.fixture(scope="module")
def basket(repo_root):
    return load_basket(repo_root / "config")


@pytest.fixture(scope="module")
def coords(repo_root):
    return load_airport_coords(repo_root / "db" / "seeds")


@pytest.fixture(scope="module")
def dataset(cfg, basket, coords):
    return generate(cfg, basket, coords, START, DAYS)


@pytest.fixture(scope="module")
def clean_quotes(dataset):
    """Quotes with the deliberately damaged rows removed."""
    damaged = set(dataset.anomalies["quote_id"])
    quotes = dataset.quotes
    return quotes[~quotes["id"].astype(str).isin(damaged)]


def test_generation_is_deterministic(cfg, basket, coords, dataset) -> None:
    """Reproducibility (CLAUDE.md principle 4): same inputs, identical output."""
    again = generate(cfg, basket, coords, START, DAYS)
    pd.testing.assert_frame_equal(dataset.quotes, again.quotes)
    pd.testing.assert_frame_equal(dataset.anomalies, again.anomalies)
    pd.testing.assert_frame_equal(dataset.sold_out, again.sold_out)


def test_quote_ids_are_unique_and_derivable(dataset) -> None:
    quotes = dataset.quotes
    assert quotes["id"].is_unique
    row = quotes.iloc[0]
    key = (
        f"{row['source_code']}|{row['route_code']}|{row['flight_number']}"
        f"|{row['query_date']}|{row['travel_date']}"
    )
    assert uuid.uuid5(SYNTHETIC_UUID_NAMESPACE, key) == row["id"]


def test_haversine_matches_a_known_distance() -> None:
    # DEL-BOM great-circle distance is about 1150 km.
    assert haversine_km(28.5562, 77.1000, 19.0887, 72.8679) == pytest.approx(1150, abs=30)


def test_lead_time_multiplier_shape(cfg) -> None:
    """Flat far out, gentle to T+7, steep inside T+3 — as configured, via interpolation."""
    import numpy as np

    days = np.array([60, 30, 14, 7, 3, 1], dtype=np.int64)
    m = lead_time_multipliers(cfg, days)
    assert (m[1:] > m[:-1]).all(), "multiplier must rise toward departure"
    flat_ratio = m[1] / m[0]  # T+30 vs T+60
    steep_ratio = m[5] / m[4]  # T+1 vs T+3
    assert flat_ratio < 1.1
    assert steep_ratio > 1.2


def test_median_fare_rises_monotonically_toward_departure(clean_quotes) -> None:
    medians = clean_quotes.groupby("advance_days")["total_fare"].median().sort_index()
    assert (medians.diff().dropna() < 0).all(), medians


def test_friday_and_sunday_travel_peaks(clean_quotes) -> None:
    dow = (
        clean_quotes.assign(dow=[d.weekday() for d in clean_quotes["travel_date"]])
        .groupby("dow")["total_fare"]
        .median()
    )
    for peak in (4, 6):  # Friday, Sunday
        for trough in (1, 2):  # Tuesday, Wednesday
            assert dow[peak] > dow[trough]


def test_festival_window_carries_a_surge(cfg, clean_quotes) -> None:
    festival = next(f for f in cfg.festivals if f.name.startswith("Independence"))
    window = {
        festival.date + timedelta(days=offset)
        for offset in range(-festival.days_before, festival.days_after + 1)
    }
    at_adv = clean_quotes[clean_quotes["advance_days"] == 45]
    inside = at_adv[at_adv["travel_date"].isin(window)]["total_fare"].median()
    nearby = {festival.date + timedelta(days=o) for o in range(-10, 11)} - window
    outside = at_adv[at_adv["travel_date"].isin(nearby)]["total_fare"].median()
    assert inside > outside * 1.05


def test_longer_routes_cost_more(clean_quotes) -> None:
    at_adv = clean_quotes[clean_quotes["advance_days"] == 45]
    med = at_adv.groupby("route_code")["base_fare"].median()
    assert med["DEL-GAU"] > med["DEL-LKO"]  # ~1500 km vs ~500 km
    assert med["DEL-COK"] > med["DEL-AMD"]


def test_fare_component_structure(cfg, clean_quotes) -> None:
    """base + tax + UDF + convenience fee = total, with the configured parameters."""
    q = clean_quotes
    reconstructed = q["base_fare"] + q["taxes"] + q["udf"] + q["convenience_fee"]
    assert (reconstructed - q["total_fare"]).abs().max() < 0.03
    assert (q["taxes"] - q["base_fare"] * cfg.pricing.tax_rate).abs().max() < 0.01
    for origin, group in q.groupby("origin_iata"):
        assert group["udf"].nunique() == 1
        assert group["udf"].iloc[0] == pytest.approx(float(cfg.udf_for(str(origin))))
    fees = q.groupby("source_code")["convenience_fee"].unique()
    for source in cfg.sources:
        assert list(fees[source.code]) == [pytest.approx(source.convenience_fee_inr)]


def test_sell_outs_cluster_near_departure(dataset) -> None:
    sold_out = dataset.sold_out
    assert len(sold_out) > 0, "a realistic scenario must contain sell-outs"
    assert sold_out["advance_days"].max() <= 18
    assert (sold_out["advance_days"] <= 5).mean() > 0.8


def test_sold_out_cells_are_really_missing(dataset) -> None:
    """A sell-out is an absent observation, not a cheap or zero fare."""
    quotes = dataset.quotes
    observed = set(
        zip(
            quotes["route_code"],
            quotes["flight_number"],
            quotes["query_date"],
            quotes["travel_date"],
            strict=True,
        )
    )
    for row in dataset.sold_out.itertuples(index=False):
        key = (row.route_code, row.flight_number, row.query_date, row.travel_date)
        assert key not in observed


def test_ground_truth_matches_the_damage_done(cfg, dataset) -> None:
    truth = dataset.anomalies
    quotes = dataset.quotes.set_index(dataset.quotes["id"].astype(str))

    expected: dict[str, int] = {}
    for spec in cfg.anomalies:
        if spec.kind is AnomalyKind.STALE_REPEAT:
            expected[spec.kind.value] = spec.count * (spec.run_length_days - 1)
        else:
            expected[spec.kind.value] = spec.count
    assert truth["kind"].value_counts().to_dict() == expected

    assert truth["quote_id"].is_unique
    for row in truth.itertuples(index=False):
        quote = quotes.loc[row.quote_id]
        assert float(quote["total_fare"]) == pytest.approx(row.injected_value, abs=0.01)
        assert row.original_value != row.injected_value


def test_component_mismatch_rows_do_not_add_up(dataset) -> None:
    truth = dataset.anomalies
    quotes = dataset.quotes.set_index(dataset.quotes["id"].astype(str))
    mismatch_ids = truth.loc[truth["kind"] == "COMPONENT_MISMATCH", "quote_id"]
    assert len(mismatch_ids) > 0
    for quote_id in mismatch_ids:
        quote = quotes.loc[quote_id]
        parts = float(quote["base_fare"] + quote["taxes"] + quote["udf"] + quote["convenience_fee"])
        assert abs(float(quote["total_fare"]) - parts) > 1.0


def test_stale_runs_freeze_consecutive_collection_days(dataset) -> None:
    truth = dataset.anomalies
    stale = truth[truth["kind"] == "STALE_REPEAT"]
    assert len(stale) > 0
    for _, group in stale.groupby("anomaly_id"):
        assert group["injected_value"].nunique() == 1
        days = sorted(date.fromisoformat(d) for d in group["query_date"])
        deltas = {(b - a).days for a, b in itertools.pairwise(days)}
        assert deltas == {1}, "a stale run must cover consecutive collection days"
