"""Stage 4 — not-collected vs sold-out vs malformed, imputation and coverage."""

from __future__ import annotations

import pandas as pd
import pytest

from apix_core.clean.missing import (
    classify_missing_cells,
    compute_coverage,
    impute_sold_out,
    quarantine_malformed,
    with_carrier_type,
)

CARRIER_TYPE = {"AI": "FSC", "6E": "LCC"}


def _expected_grid() -> pd.DataFrame:
    rows = []
    for carrier, flight in (("AI", "AI101"), ("6E", "6E202")):
        for query_date, travel_date in (
            ("2026-09-01", "2026-09-06"),
            ("2026-09-02", "2026-09-07"),
            ("2026-09-03", "2026-09-08"),
        ):
            rows.append(
                {
                    "source_id": "s1",
                    "route_id": "DEL-BOM",
                    "carrier_iata": carrier,
                    "flight_number": flight,
                    "advance_days": 5,
                    "query_date": query_date,
                    "travel_date": travel_date,
                }
            )
    return pd.DataFrame(rows)


def _observed_ai_only() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_id": ["s1"] * 3,
            "route_id": ["DEL-BOM"] * 3,
            "carrier_iata": ["AI"] * 3,
            "flight_number": ["AI101"] * 3,
            "advance_days": [5] * 3,
            "query_date": ["2026-09-01", "2026-09-02", "2026-09-03"],
            "travel_date": ["2026-09-06", "2026-09-07", "2026-09-08"],
            "total_fare": [5000.0, 5100.0, 4900.0],
        }
    )


def _runs_all_succeeded() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_id": ["s1"] * 3,
            "route_id": ["DEL-BOM"] * 3,
            "query_date": ["2026-09-01", "2026-09-02", "2026-09-03"],
            "status": ["SUCCEEDED"] * 3,
        }
    )


class TestClassifyMissingCells:
    def test_blocked_run_is_not_collected(self) -> None:
        runs = _runs_all_succeeded()
        runs.loc[runs["query_date"] == "2026-09-02", "status"] = "BLOCKED"
        missing = classify_missing_cells(_expected_grid(), _observed_ai_only(), runs)
        row = missing[(missing.carrier_iata == "6E") & (missing.query_date == "2026-09-02")]
        assert row["missing_reason"].item() == "not_collected"

    def test_succeeded_run_with_no_observation_is_sold_out(self) -> None:
        missing = classify_missing_cells(
            _expected_grid(), _observed_ai_only(), _runs_all_succeeded()
        )
        six_e_rows = missing[missing.carrier_iata == "6E"]
        assert (six_e_rows["missing_reason"] == "sold_out").all()
        assert len(six_e_rows) == 3

    def test_no_run_record_at_all_is_not_collected(self) -> None:
        runs = _runs_all_succeeded().iloc[0:0]  # no runs recorded
        missing = classify_missing_cells(_expected_grid(), _observed_ai_only(), runs)
        assert (missing["missing_reason"] == "not_collected").all()

    def test_observed_cells_are_not_reported_as_missing(self) -> None:
        missing = classify_missing_cells(
            _expected_grid(), _observed_ai_only(), _runs_all_succeeded()
        )
        observed_keys = set(
            zip(
                _observed_ai_only()["carrier_iata"],
                _observed_ai_only()["query_date"],
                strict=True,
            )
        )
        missing_keys = set(zip(missing["carrier_iata"], missing["query_date"], strict=True))
        assert not (observed_keys & missing_keys)

    def test_missing_required_columns_raise(self) -> None:
        bad = _expected_grid().drop(columns=["carrier_iata"])
        with pytest.raises(ValueError, match="expected_cells missing"):
            classify_missing_cells(bad, _observed_ai_only(), _runs_all_succeeded())

    def test_observed_missing_required_columns_raises(self) -> None:
        bad_observed = _observed_ai_only().drop(columns=["carrier_iata"])
        with pytest.raises(ValueError, match="observed missing"):
            classify_missing_cells(_expected_grid(), bad_observed, _runs_all_succeeded())

    def test_collection_runs_missing_required_columns_raises(self) -> None:
        bad_runs = _runs_all_succeeded().drop(columns=["status"])
        with pytest.raises(ValueError, match="collection_runs missing"):
            classify_missing_cells(_expected_grid(), _observed_ai_only(), bad_runs)

    def test_fully_covered_grid_returns_empty_with_missing_reason_column(self) -> None:
        full_observed = _expected_grid().assign(total_fare=5000.0)
        missing = classify_missing_cells(_expected_grid(), full_observed, _runs_all_succeeded())
        assert missing.empty
        assert "missing_reason" in missing.columns


class TestImputeSoldOut:
    def test_group_with_enough_evidence_is_imputed_with_the_mean(self) -> None:
        sold_out = with_carrier_type(
            pd.DataFrame(
                {
                    "route_id": ["DEL-BOM"],
                    "advance_days": [5],
                    "carrier_iata": ["AI"],
                }
            ),
            CARRIER_TYPE,
        )
        clean = with_carrier_type(_observed_ai_only(), CARRIER_TYPE)
        result = impute_sold_out(sold_out, clean, min_group_size=3)
        assert len(result.imputed) == 1
        assert result.imputed["total_fare"].iloc[0] == pytest.approx(5000.0)
        assert bool(result.imputed["is_imputed"].iloc[0]) is True
        assert result.imputed["imputation_method"].iloc[0] == "cell_mean"
        assert result.unresolved.empty

    def test_group_below_min_size_is_unresolved_not_guessed(self) -> None:
        sold_out = with_carrier_type(
            pd.DataFrame({"route_id": ["DEL-BOM"], "advance_days": [5], "carrier_iata": ["6E"]}),
            CARRIER_TYPE,
        )
        clean = with_carrier_type(_observed_ai_only(), CARRIER_TYPE)  # no 6E observations at all
        result = impute_sold_out(sold_out, clean, min_group_size=3)
        assert result.imputed.empty
        assert len(result.unresolved) == 1

    def test_outliers_must_be_excluded_by_the_caller(self) -> None:
        """The mean is only as clean as what's passed in — an included outlier pulls it."""
        sold_out = with_carrier_type(
            pd.DataFrame({"route_id": ["DEL-BOM"], "advance_days": [5], "carrier_iata": ["AI"]}),
            CARRIER_TYPE,
        )
        polluted = _observed_ai_only().copy()
        polluted.loc[0, "total_fare"] = 500000.0
        clean = with_carrier_type(polluted, CARRIER_TYPE)
        result = impute_sold_out(sold_out, clean, min_group_size=3)
        assert result.imputed["total_fare"].iloc[0] > 100000.0

    def test_empty_sold_out_returns_empty_results(self) -> None:
        empty = with_carrier_type(
            pd.DataFrame(columns=["route_id", "advance_days", "carrier_iata"]), CARRIER_TYPE
        )
        clean = with_carrier_type(_observed_ai_only(), CARRIER_TYPE)
        result = impute_sold_out(empty, clean, min_group_size=3)
        assert result.imputed.empty
        assert result.unresolved.empty

    def test_sold_out_cells_missing_group_columns_raises(self) -> None:
        bad = pd.DataFrame({"route_id": ["DEL-BOM"], "advance_days": [5]})  # no carrier_type
        clean = with_carrier_type(_observed_ai_only(), CARRIER_TYPE)
        with pytest.raises(ValueError, match="sold_out_cells missing"):
            impute_sold_out(bad, clean, min_group_size=3)

    def test_clean_quotes_missing_group_columns_raises(self) -> None:
        sold_out = with_carrier_type(
            pd.DataFrame({"route_id": ["DEL-BOM"], "advance_days": [5], "carrier_iata": ["AI"]}),
            CARRIER_TYPE,
        )
        bad_clean = _observed_ai_only().drop(columns=["total_fare"])
        with pytest.raises(ValueError, match="clean_quotes missing"):
            impute_sold_out(sold_out, bad_clean, min_group_size=3)


class TestWithCarrierType:
    def test_missing_carrier_iata_raises(self) -> None:
        with pytest.raises(ValueError, match="missing carrier_iata"):
            with_carrier_type(pd.DataFrame({"route_id": ["r1"]}), CARRIER_TYPE)


class TestQuarantineMalformed:
    def test_missing_required_columns_raises(self) -> None:
        bad = pd.DataFrame({"route_id": ["r1"], "carrier_iata": ["AI"]})
        with pytest.raises(ValueError, match="missing required columns"):
            quarantine_malformed(bad)

    def test_negative_total_fare_is_quarantined(self) -> None:
        quotes = pd.DataFrame(
            {
                "route_id": ["r1"],
                "carrier_iata": ["AI"],
                "travel_date": ["2026-09-06"],
                "advance_days": [5],
                "total_fare": [-100.0],
            }
        )
        kept, quarantined = quarantine_malformed(quotes)
        assert kept.empty
        assert quarantined["quarantine_reason"].iloc[0] == "invalid_total_fare"

    def test_zero_total_fare_is_quarantined(self) -> None:
        quotes = pd.DataFrame(
            {
                "route_id": ["r1"],
                "carrier_iata": ["AI"],
                "travel_date": ["2026-09-06"],
                "advance_days": [5],
                "total_fare": [0.0],
            }
        )
        kept, _ = quarantine_malformed(quotes)
        assert kept.empty

    def test_missing_route_id_is_quarantined(self) -> None:
        quotes = pd.DataFrame(
            {
                "route_id": [None],
                "carrier_iata": ["AI"],
                "travel_date": ["2026-09-06"],
                "advance_days": [5],
                "total_fare": [5000.0],
            }
        )
        kept, quarantined = quarantine_malformed(quotes)
        assert kept.empty
        assert quarantined["quarantine_reason"].iloc[0] == "missing_identity_dimension"

    def test_valid_row_is_kept(self) -> None:
        quotes = pd.DataFrame(
            {
                "route_id": ["r1"],
                "carrier_iata": ["AI"],
                "travel_date": ["2026-09-06"],
                "advance_days": [5],
                "total_fare": [5000.0],
            }
        )
        kept, quarantined = quarantine_malformed(quotes)
        assert len(kept) == 1
        assert quarantined.empty

    def test_empty_input(self) -> None:
        empty = pd.DataFrame(
            columns=["route_id", "carrier_iata", "travel_date", "advance_days", "total_fare"]
        )
        kept, quarantined = quarantine_malformed(empty)
        assert kept.empty
        assert "quarantine_reason" in quarantined.columns


class TestComputeCoverage:
    def test_coverage_counts_only_genuine_observations(self) -> None:
        missing = classify_missing_cells(
            _expected_grid(), _observed_ai_only(), _runs_all_succeeded()
        )
        coverage = compute_coverage(_expected_grid(), _observed_ai_only(), missing)
        row = coverage.iloc[0]
        assert row["expected_count"] == 6
        assert row["observed_count"] == 3
        assert row["sold_out_count"] == 3
        assert row["not_collected_count"] == 0
        assert row["coverage_pct"] == pytest.approx(50.0)

    def test_imputed_cells_do_not_inflate_coverage(self) -> None:
        missing = classify_missing_cells(
            _expected_grid(), _observed_ai_only(), _runs_all_succeeded()
        )
        sold_out = with_carrier_type(missing[missing.missing_reason == "sold_out"], CARRIER_TYPE)
        # One 6E observation elsewhere so the (route, advance_days, LCC) group is non-empty.
        observed_with_lcc = pd.concat(
            [
                _observed_ai_only(),
                pd.DataFrame(
                    {
                        "source_id": ["s2"],
                        "route_id": ["DEL-BOM"],
                        "carrier_iata": ["6E"],
                        "flight_number": ["6E202"],
                        "advance_days": [5],
                        "query_date": ["2026-09-01"],
                        "travel_date": ["2026-09-06"],
                        "total_fare": [4800.0],
                    }
                ),
            ],
            ignore_index=True,
        )
        clean = with_carrier_type(observed_with_lcc, CARRIER_TYPE)
        imputation = impute_sold_out(sold_out, clean, min_group_size=1)
        assert not imputation.imputed.empty  # sanity: something did get imputed
        coverage = compute_coverage(
            _expected_grid(), _observed_ai_only(), missing, imputation.imputed
        )
        assert coverage.iloc[0]["coverage_pct"] == pytest.approx(50.0)
        assert coverage.iloc[0]["imputed_count"] == 3
