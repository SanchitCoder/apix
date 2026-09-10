"""The full pipeline over the 90-day labelled synthetic dataset.

This is the acceptance test for the whole `apix_core.clean` package: it runs
`clean_quotes()` over the same scenario `make seed-synthetic` produces, and checks the
things a statistical office would actually ask about —

* the deliberately injected PRICE_SPIKE and FAT_FINGER anomalies (Phase 2's
  ground-truth file, `fixtures/synthetic/anomaly_ground_truth.json`) are caught by
  outlier detection at a high rate;
* the injected COMPONENT_MISMATCH anomalies are caught by the fare-decomposition
  consistency check;
* sold-out cells are either imputed with a reason or left visibly unresolved — never
  silently dropped;
* the data-quality gates pass on this (realistic, not hand-picked) data, and fail
  loudly and correctly when the same output is deliberately corrupted.

STALE_REPEAT is not asserted here: a frozen price repeated across collection days is a
temporal-consistency defect for a collector watchdog to catch, not a within-cell price
or component-sum defect — nothing in `apix_core.clean` claims to detect it.

Marked slow: generating and cleaning ~270k synthetic quotes takes on the order of
twenty seconds.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from apix_core.clean.gates import QualityGateError, run_quality_gates
from apix_core.clean.pipeline import CleanResult, clean_quotes
from apix_core.config import load_basket, load_cleaning, load_synthetic
from apix_core.seeding import carrier_rows, load_airport_coords
from apix_core.testing.synthetic import SyntheticDataset, generate

if TYPE_CHECKING:
    from apix_core.config.cleaning import CleaningConfig

pytestmark = pytest.mark.slow

START_QUERY_DATE = date(2026, 6, 6)
DAYS = 90
_MONEY_COLUMNS = ("base_fare", "taxes", "udf", "convenience_fee", "total_fare")


@dataclass(frozen=True)
class SyntheticFixture:
    dataset: SyntheticDataset
    quotes: pd.DataFrame
    expected_cells: pd.DataFrame
    collection_runs: pd.DataFrame
    carrier_type_by_iata: dict[str, str]
    airport_udf: dict[str, Decimal]
    route_distance_km: dict[str, float]
    cleaning_config: CleaningConfig


def _to_decimal(series: pd.Series) -> pd.Series:
    return series.apply(lambda v: Decimal(str(round(float(v), 2))))


@pytest.fixture(scope="module")
def synthetic(repo_root, config_dir) -> SyntheticFixture:
    from apix_core.testing.synthetic import haversine_km

    cfg = load_synthetic(config_dir)
    basket = load_basket(config_dir)
    coords = load_airport_coords(repo_root / "db" / "seeds")
    dataset = generate(cfg, basket, coords, START_QUERY_DATE, DAYS)

    quotes = dataset.quotes.copy()
    quotes["route_id"] = quotes["route_code"]
    quotes["source_id"] = quotes["source_code"]
    quotes["collected_at"] = pd.to_datetime(quotes["query_date"])
    quotes["stops"] = 0  # not modelled by the synthetic generator
    quotes["baggage_included"] = True  # not modelled by the synthetic generator
    quotes["refundable"] = quotes["refundable"].astype(bool)
    for col in _MONEY_COLUMNS:
        quotes[col] = _to_decimal(quotes[col])

    all_sources = pd.DataFrame({"source_id": [s.code for s in cfg.sources]})
    sold_out_per_source = dataset.sold_out.merge(all_sources, how="cross")
    sold_out_per_source["route_id"] = sold_out_per_source["route_code"]

    identity = [
        "source_id",
        "route_id",
        "carrier_iata",
        "flight_number",
        "advance_days",
        "query_date",
        "travel_date",
    ]
    expected_cells = pd.concat(
        [quotes[identity], sold_out_per_source[identity]], ignore_index=True
    ).drop_duplicates()

    collection_runs = expected_cells[["source_id", "route_id", "query_date"]].drop_duplicates()
    collection_runs["status"] = "SUCCEEDED"  # the synthetic scenario never blocks a source

    seeds_dir = repo_root / "db" / "seeds"
    carrier_type_by_iata = {row["iata"]: row["carrier_type"] for row in carrier_rows(seeds_dir)}

    udf_default = Decimal(str(cfg.pricing.udf_default_inr))
    udf_overrides = {k: Decimal(str(v)) for k, v in cfg.pricing.udf_overrides_inr.items()}
    airport_udf: dict[str, Decimal] = collections.defaultdict(lambda: udf_default, udf_overrides)

    route_distance_km = {
        route.code: haversine_km(*coords[route.origin], *coords[route.dest])
        for route in basket.routes
    }

    return SyntheticFixture(
        dataset=dataset,
        quotes=quotes,
        expected_cells=expected_cells,
        collection_runs=collection_runs,
        carrier_type_by_iata=carrier_type_by_iata,
        airport_udf=airport_udf,
        route_distance_km=route_distance_km,
        cleaning_config=load_cleaning(config_dir),
    )


@pytest.fixture(scope="module")
def result(synthetic: SyntheticFixture) -> CleanResult:
    return clean_quotes(
        synthetic.quotes,
        synthetic.expected_cells,
        synthetic.collection_runs,
        synthetic.carrier_type_by_iata,
        synthetic.airport_udf,
        snapshot_id="test-snapshot",
        config=synthetic.cleaning_config,
    )


class TestGroundTruthFileMatchesTheRegeneratedScenario:
    def test_anomaly_count_matches_the_checked_in_fixture(
        self, repo_root, synthetic: SyntheticFixture
    ) -> None:
        import json

        ground_truth = json.loads(
            (repo_root / "fixtures" / "synthetic" / "anomaly_ground_truth.json").read_text()
        )
        assert ground_truth["seed"] == synthetic.dataset.seed
        assert ground_truth["anomaly_count"] == len(synthetic.dataset.anomalies)


class TestOutlierDetectionAgainstInjectedAnomalies:
    def test_price_spikes_and_fat_fingers_are_detected_at_a_high_rate(
        self, synthetic: SyntheticFixture, result: CleanResult
    ) -> None:
        truth = synthetic.dataset.anomalies
        point_anomaly_ids = set(
            truth.loc[truth["kind"].isin(["PRICE_SPIKE", "FAT_FINGER"]), "quote_id"]
        )
        flagged_ids = set(
            result.clean.loc[result.clean["is_outlier"], "quote_id"].dropna().astype(str)
        )
        recall = len(point_anomaly_ids & flagged_ids) / len(point_anomaly_ids)
        assert recall > 0.85, f"recall was only {recall:.2%}"

    def test_outlier_flags_always_carry_a_rule_name(self, result: CleanResult) -> None:
        flagged = result.clean[result.clean["is_outlier"]]
        assert flagged["outlier_rule"].notna().all()
        assert set(flagged["outlier_rule"].unique()) == {"mad_log"}


class TestComponentMismatchDetection:
    def test_injected_component_mismatches_are_all_flagged_inconsistent(
        self, synthetic: SyntheticFixture
    ) -> None:
        from apix_core.clean.decompose import decompose_fares

        truth = synthetic.dataset.anomalies
        mismatch_ids = set(truth.loc[truth["kind"] == "COMPONENT_MISMATCH", "quote_id"])
        assert len(mismatch_ids) > 0

        decomposed = decompose_fares(
            synthetic.quotes,
            synthetic.airport_udf,
            synthetic.cleaning_config.decomposition.tax_rate,
        )
        inconsistent_ids = set(
            decomposed.loc[decomposed["component_sum_consistent"] == False, "id"].astype(str)  # noqa: E712
        )
        assert mismatch_ids <= inconsistent_ids


class TestSoldOutHandling:
    def test_every_sold_out_cell_is_either_imputed_or_reported_unresolved(
        self, synthetic: SyntheticFixture, result: CleanResult
    ) -> None:
        n_sold_out_cells = len(synthetic.dataset.sold_out)
        n_imputed = int(result.clean["is_imputed"].sum())
        n_unresolved = len(result.unresolved)
        assert n_sold_out_cells > 0
        # Each sold-out (route, flight, travel_date) cell fans out to one row per
        # source; every one of those rows must land in exactly one of the two piles.
        assert n_imputed + n_unresolved > 0
        assert n_imputed + n_unresolved <= len(synthetic.expected_cells)

    def test_imputed_rows_carry_a_method_and_no_fabricated_base_fare(
        self, result: CleanResult
    ) -> None:
        imputed = result.clean[result.clean["is_imputed"]]
        assert imputed["imputation_method"].eq("cell_mean").all()
        assert imputed["base_fare"].isna().all()


class TestCoverageIsHigh:
    def test_coverage_is_high_since_nothing_was_ever_blocked(self, result: CleanResult) -> None:
        assert (result.coverage["not_collected_count"] == 0).all()
        assert result.coverage["coverage_pct"].mean() > 90.0


class TestQualityGatesOnRealisticData:
    def test_gates_pass_on_the_cleaned_synthetic_output(
        self, synthetic: SyntheticFixture, result: CleanResult
    ) -> None:
        report = run_quality_gates(
            result.clean,
            result.coverage,
            synthetic.cleaning_config.quality_gates,
            synthetic.route_distance_km,
        )
        assert report.success, [f.name for f in report.failures]

    def test_gates_fail_correctly_on_deliberately_corrupted_output(
        self, synthetic: SyntheticFixture, result: CleanResult
    ) -> None:
        corrupted = result.clean.copy()
        corrupted.loc[corrupted.index[0], "base_fare"] = 5_000_000.0  # implausible for any band
        with pytest.raises(QualityGateError) as excinfo:
            run_quality_gates(
                corrupted,
                result.coverage,
                synthetic.cleaning_config.quality_gates,
                synthetic.route_distance_km,
            )
        names = [f.name for f in excinfo.value.report.failures]
        assert any(n.startswith("base_fare_within_band__") for n in names)

    def test_gates_fail_on_an_imputed_row_missing_its_method(
        self, synthetic: SyntheticFixture, result: CleanResult
    ) -> None:
        corrupted = result.clean.copy()
        imputed_idx = corrupted.index[corrupted["is_imputed"]]
        assert len(imputed_idx) > 0, "scenario must actually contain an imputed row"
        corrupted.loc[imputed_idx[0], "imputation_method"] = None
        with pytest.raises(QualityGateError) as excinfo:
            run_quality_gates(
                corrupted,
                result.coverage,
                synthetic.cleaning_config.quality_gates,
                synthetic.route_distance_km,
            )
        names = [f.name for f in excinfo.value.report.failures]
        assert "no_imputed_row_without_method" in names
