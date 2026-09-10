"""Stage 3 — outlier screening: both rules always computed, only one gates."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apix_core.clean.outliers import detect_outliers
from apix_core.config.cleaning import OutlierRuleName


def _cell(prices: list[float], **overrides: object) -> pd.DataFrame:
    n = len(prices)
    base = {
        "route_id": ["r1"] * n,
        "advance_days": [5] * n,
        "travel_date": ["2026-09-10"] * n,
        "total_fare": prices,
    }
    base.update(overrides)
    return pd.DataFrame(base)


def _normal_cell(
    n: int = 20, spike_at: int | None = None, spike_factor: float = 10.0
) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    prices = list(rng.normal(5000, 100, n))
    if spike_at is not None:
        prices[spike_at] *= spike_factor
    return _cell(prices)


class TestBothRulesAreAlwaysComputed:
    def test_mad_and_iqr_columns_both_appear_regardless_of_active_rule(self) -> None:
        out = detect_outliers(
            _normal_cell(spike_at=0), OutlierRuleName.MAD_LOG, 3.5, 1.5, min_cell_size=5
        )
        assert {"is_outlier_mad", "is_outlier_iqr", "is_outlier", "outlier_rule"} <= set(
            out.columns
        )

    def test_a_gross_spike_is_caught_by_both_rules(self) -> None:
        out = detect_outliers(
            _normal_cell(spike_at=0), OutlierRuleName.MAD_LOG, 3.5, 1.5, min_cell_size=5
        )
        assert bool(out.loc[0, "is_outlier_mad"])
        assert bool(out.loc[0, "is_outlier_iqr"])


class TestActiveRuleGates:
    def test_active_rule_mad_log_sets_is_outlier_and_names_itself(self) -> None:
        out = detect_outliers(
            _normal_cell(spike_at=0), OutlierRuleName.MAD_LOG, 3.5, 1.5, min_cell_size=5
        )
        assert bool(out.loc[0, "is_outlier"])
        assert out.loc[0, "outlier_rule"] == "mad_log"

    def test_active_rule_iqr_sets_is_outlier_and_names_itself(self) -> None:
        out = detect_outliers(
            _normal_cell(spike_at=0), OutlierRuleName.IQR, 3.5, 1.5, min_cell_size=5
        )
        assert bool(out.loc[0, "is_outlier"])
        assert out.loc[0, "outlier_rule"] == "iqr"

    def test_non_flagged_rows_have_no_outlier_rule(self) -> None:
        out = detect_outliers(
            _normal_cell(spike_at=0), OutlierRuleName.MAD_LOG, 3.5, 1.5, min_cell_size=5
        )
        assert out.loc[1, "outlier_rule"] is None or pd.isna(out.loc[1, "outlier_rule"])


class TestNothingIsDropped:
    def test_row_count_is_unchanged(self) -> None:
        quotes = _normal_cell(spike_at=0)
        out = detect_outliers(quotes, OutlierRuleName.MAD_LOG, 3.5, 1.5, min_cell_size=5)
        assert len(out) == len(quotes)


class TestSmallCells:
    def test_cells_below_min_size_are_never_screened(self) -> None:
        tiny = _cell([1000.0, 1000000.0, 1000.0])  # extreme spread, but n=3
        out = detect_outliers(tiny, OutlierRuleName.MAD_LOG, 3.5, 1.5, min_cell_size=5)
        assert not out["is_outlier"].any()

    def test_cell_at_exactly_min_size_is_screened(self) -> None:
        prices = [4950.0, 5000.0, 5050.0, 4980.0, 500000.0]
        out = detect_outliers(_cell(prices), OutlierRuleName.MAD_LOG, 3.5, 1.5, min_cell_size=5)
        assert bool(out.loc[4, "is_outlier"])


class TestZeroSpread:
    def test_a_flat_cell_flags_nothing_under_mad(self) -> None:
        flat = _cell([5000.0] * 10)
        out = detect_outliers(flat, OutlierRuleName.MAD_LOG, 3.5, 1.5, min_cell_size=5)
        assert not out["is_outlier_mad"].any()


class TestValidation:
    def test_missing_required_column_raises(self) -> None:
        quotes = _normal_cell().drop(columns=["advance_days"])
        with pytest.raises(ValueError, match="missing required columns"):
            detect_outliers(quotes, OutlierRuleName.MAD_LOG, 3.5, 1.5, min_cell_size=5)

    def test_min_cell_size_below_two_raises(self) -> None:
        with pytest.raises(ValueError, match="min_cell_size"):
            detect_outliers(_normal_cell(), OutlierRuleName.MAD_LOG, 3.5, 1.5, min_cell_size=1)

    def test_empty_input_returns_empty_with_new_columns(self) -> None:
        empty = _normal_cell().iloc[0:0]
        out = detect_outliers(empty, OutlierRuleName.MAD_LOG, 3.5, 1.5, min_cell_size=5)
        assert out.empty
        assert {"is_outlier_mad", "is_outlier_iqr", "is_outlier", "outlier_rule"} <= set(
            out.columns
        )
