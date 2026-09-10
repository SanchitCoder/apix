"""Booking-profile (lead-time) window weighting.

Worked example — three advance-purchase windows, full coverage:

    index_by_window = {AP00_03: 1.10, AP04_07: 1.05, AP08_14: 0.95}
    weights         = {AP00_03: 0.5,  AP04_07: 0.3,  AP08_14: 0.2}

    combined = exp(0.5*ln(1.10) + 0.3*ln(1.05) + 0.2*ln(0.95)) = 1.0534110104
    coverage_pct = 100.0 (every configured window has data)

Partial coverage — AP08_14 missing from the data this period:

    matched weight mass = 0.5 + 0.3 = 0.8 of the configured 1.0 -> coverage_pct = 80.0
    renormalised weights = [0.5/0.8, 0.3/0.8] = [0.625, 0.375]
    combined = exp(0.625*ln(1.10) + 0.375*ln(1.05)) = 1.0809769050
"""

from __future__ import annotations

import pandas as pd
import pytest

from apix_core.index.weighting import combine_advance_windows

WEIGHTS = {"AP00_03": 0.5, "AP04_07": 0.3, "AP08_14": 0.2}


class TestGolden:
    def test_full_coverage(self) -> None:
        index_by_window = pd.Series({"AP00_03": 1.10, "AP04_07": 1.05, "AP08_14": 0.95})
        combined, coverage_pct = combine_advance_windows(index_by_window, WEIGHTS)
        assert combined == pytest.approx(1.0534110104, abs=1e-9)
        assert coverage_pct == pytest.approx(100.0)

    def test_partial_coverage_renormalises_and_reports_the_gap(self) -> None:
        index_by_window = pd.Series({"AP00_03": 1.10, "AP04_07": 1.05})
        combined, coverage_pct = combine_advance_windows(index_by_window, WEIGHTS)
        assert coverage_pct == pytest.approx(80.0)
        assert combined == pytest.approx(1.0809769050, abs=1e-9)


class TestProperties:
    def test_identical_index_values_combine_to_exactly_that_value(self) -> None:
        index_by_window = pd.Series({"AP00_03": 1.234, "AP04_07": 1.234, "AP08_14": 1.234})
        combined, coverage_pct = combine_advance_windows(index_by_window, WEIGHTS)
        assert combined == pytest.approx(1.234, abs=1e-10)
        assert coverage_pct == pytest.approx(100.0)

    def test_equal_prices_give_exactly_one(self) -> None:
        index_by_window = pd.Series({"AP00_03": 1.0, "AP04_07": 1.0, "AP08_14": 1.0})
        combined, _ = combine_advance_windows(index_by_window, WEIGHTS)
        assert combined == 1.0


class TestValidation:
    def test_empty_index_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one entry"):
            combine_advance_windows(pd.Series(dtype=float), WEIGHTS)

    def test_no_matching_window_rejected(self) -> None:
        index_by_window = pd.Series({"AP61_90": 1.1})
        with pytest.raises(ValueError, match="no advance-purchase window"):
            combine_advance_windows(index_by_window, WEIGHTS)

    def test_non_positive_index_value_rejected(self) -> None:
        index_by_window = pd.Series({"AP00_03": 0.0})
        with pytest.raises(ValueError, match="positive"):
            combine_advance_windows(index_by_window, WEIGHTS)

    def test_negative_weight_rejected(self) -> None:
        index_by_window = pd.Series({"AP00_03": 1.1})
        with pytest.raises(ValueError, match="non-negative"):
            combine_advance_windows(index_by_window, {"AP00_03": -1.0})

    def test_empty_weights_rejected(self) -> None:
        index_by_window = pd.Series({"AP00_03": 1.1})
        with pytest.raises(ValueError, match="weights must not be empty"):
            combine_advance_windows(index_by_window, {})

    def test_all_zero_weights_rejected(self) -> None:
        index_by_window = pd.Series({"AP00_03": 1.1})
        with pytest.raises(ValueError, match="positive total"):
            combine_advance_windows(index_by_window, {"AP00_03": 0.0})
