"""Data-quality gates: pass on clean data, fail correctly and loudly on corrupted data."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from apix_core.clean.gates import QualityGateError, run_quality_gates
from apix_core.config import load_cleaning

if TYPE_CHECKING:
    from apix_core.config.cleaning import QualityGateConfig


@pytest.fixture(scope="module")
def gate_config(config_dir) -> QualityGateConfig:
    return load_cleaning(config_dir).quality_gates


def _clean_quotes(n: int = 5) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "quote_id": [str(uuid.uuid4()) for _ in range(n)],
            "route_id": ["r1"] * n,
            "base_fare": [4000.0, 4200.0, 4100.0, 3900.0, 4050.0][:n],
            "taxes": [200.0, 210.0, 205.0, 195.0, 202.0][:n],
            "total_fare": [4550.0, 4760.0, 4655.0, 4445.0, 4602.0][:n],
            "is_outlier": [False] * n,
            "is_imputed": [False] * n,
            "imputation_method": [None] * n,
        }
    )


def _coverage(pct: float = 85.0) -> pd.DataFrame:
    return pd.DataFrame({"route_id": ["r1"], "advance_days": [5], "coverage_pct": [pct]})


ROUTE_DISTANCE = {"r1": 1100.0}


class TestPassingData:
    def test_all_gates_pass_on_well_formed_data(self, gate_config: QualityGateConfig) -> None:
        report = run_quality_gates(_clean_quotes(), _coverage(), gate_config, ROUTE_DISTANCE)
        assert report.success
        assert len(report.results) == 7  # 3 distance bands + 4 other gates
        assert report.failures == []


class TestBaseFareOutOfBand:
    def test_a_gross_base_fare_fails_its_band_and_raises(
        self, gate_config: QualityGateConfig
    ) -> None:
        bad = _clean_quotes()
        bad.loc[0, "base_fare"] = 999999.0  # far above any distance band's max
        with pytest.raises(QualityGateError) as excinfo:
            run_quality_gates(bad, _coverage(), gate_config, ROUTE_DISTANCE)
        names = [f.name for f in excinfo.value.report.failures]
        assert any(n.startswith("base_fare_within_band__") for n in names)

    def test_unknown_route_raises_a_plain_value_error(self, gate_config: QualityGateConfig) -> None:
        with pytest.raises(ValueError, match="missing routes"):
            run_quality_gates(_clean_quotes(), _coverage(), gate_config, {})


class TestTaxShareOutOfBand:
    def test_an_implausible_tax_share_fails(self, gate_config: QualityGateConfig) -> None:
        bad = _clean_quotes()
        bad.loc[0, "taxes"] = bad.loc[0, "total_fare"] * 0.9  # way above tax_share_max
        with pytest.raises(QualityGateError) as excinfo:
            run_quality_gates(bad, _coverage(), gate_config, ROUTE_DISTANCE)
        names = [f.name for f in excinfo.value.report.failures]
        assert "tax_share_within_band" in names


class TestCoverageFloor:
    def test_coverage_below_floor_fails(self, gate_config: QualityGateConfig) -> None:
        with pytest.raises(QualityGateError) as excinfo:
            run_quality_gates(_clean_quotes(), _coverage(pct=5.0), gate_config, ROUTE_DISTANCE)
        names = [f.name for f in excinfo.value.report.failures]
        assert "coverage_above_floor" in names


class TestDuplicateQuoteId:
    def test_duplicate_quote_id_fails(self, gate_config: QualityGateConfig) -> None:
        bad = _clean_quotes()
        bad.loc[1, "quote_id"] = bad.loc[0, "quote_id"]
        with pytest.raises(QualityGateError) as excinfo:
            run_quality_gates(bad, _coverage(), gate_config, ROUTE_DISTANCE)
        names = [f.name for f in excinfo.value.report.failures]
        assert "no_duplicate_quote_id" in names

    def test_multiple_null_quote_ids_are_not_flagged_as_duplicates(
        self, gate_config: QualityGateConfig
    ) -> None:
        """Imputed rows all carry quote_id = null; that must never collide."""
        quotes = _clean_quotes()
        quotes["quote_id"] = [None, None, *quotes["quote_id"].iloc[2:]]
        report = run_quality_gates(quotes, _coverage(), gate_config, ROUTE_DISTANCE)
        assert report.success


class TestImputedWithoutMethod:
    def test_imputed_row_without_a_method_fails(self, gate_config: QualityGateConfig) -> None:
        bad = _clean_quotes()
        bad.loc[0, "is_imputed"] = True
        bad.loc[0, "imputation_method"] = None
        with pytest.raises(QualityGateError) as excinfo:
            run_quality_gates(bad, _coverage(), gate_config, ROUTE_DISTANCE)
        names = [f.name for f in excinfo.value.report.failures]
        assert "no_imputed_row_without_method" in names

    def test_imputed_row_with_a_method_passes(self, gate_config: QualityGateConfig) -> None:
        ok = _clean_quotes()
        ok.loc[0, "is_imputed"] = True
        ok.loc[0, "imputation_method"] = "cell_mean"
        report = run_quality_gates(ok, _coverage(), gate_config, ROUTE_DISTANCE)
        assert report.success


class TestReportShowsEveryFailureNotJustTheFirst:
    def test_multiple_simultaneous_failures_are_all_reported(
        self, gate_config: QualityGateConfig
    ) -> None:
        bad = _clean_quotes()
        bad.loc[0, "base_fare"] = 999999.0
        bad.loc[1, "is_imputed"] = True
        bad.loc[1, "imputation_method"] = None
        with pytest.raises(QualityGateError) as excinfo:
            run_quality_gates(bad, _coverage(pct=1.0), gate_config, ROUTE_DISTANCE)
        names = {f.name for f in excinfo.value.report.failures}
        assert "coverage_above_floor" in names
        assert "no_imputed_row_without_method" in names
        assert any(n.startswith("base_fare_within_band__") for n in names)
