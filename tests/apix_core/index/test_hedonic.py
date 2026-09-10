"""Time-dummy hedonic quality adjustment.

Worked example 1 — a pure, uniform price increase with no composition change:

    period 0: eco x2 @ 100, biz x2 @ 300
    period 1: eco x2 @ 110, biz x2 @ 330   (every price scaled by exactly 1.1)

    The design is a perfect fit (R^2 = 1): the time-dummy coefficient for period 1 is
    exactly ln(1.1), so the quality-adjusted index is exactly 1.1 — matching the true
    uniform price move regardless of the eco/biz mix.

Worked example 2 — a pure composition shift with *no* true price change:

    period 0: eco x3 @ 100, biz x1 @ 300  -> naive mean price = 150
    period 1: eco x1 @ 100, biz x3 @ 300  -> naive mean price = 250

    Per-class prices are identical in both periods; only the mix shifted toward the
    more expensive class. A naive average would show a 67% increase. The hedonic
    time-dummy coefficient for period 1 is exactly 0 (index = 1.0, R^2 = 1): quality
    adjustment correctly reports no price change. This is precisely what
    CLAUDE.md/the task spec mean by "quality adjustment" — holding the mix constant.
"""

from __future__ import annotations

import pandas as pd
import pytest

from apix_core.index.hedonic import HedonicQualityFloorError, hedonic_time_dummy


def _uniform_increase_panel() -> pd.DataFrame:
    rows = []
    for period, mult in ((0, 1.0), (1, 1.1)):
        for cls, base in (("eco", 100.0), ("biz", 300.0)):
            rows.extend([{"period": period, "cls": cls, "total_fare": base * mult}] * 2)
    return pd.DataFrame(rows)


def _composition_shift_panel() -> pd.DataFrame:
    rows = (
        [{"period": 0, "cls": "eco", "total_fare": 100.0}] * 3
        + [{"period": 0, "cls": "biz", "total_fare": 300.0}]
        + [{"period": 1, "cls": "eco", "total_fare": 100.0}]
        + [{"period": 1, "cls": "biz", "total_fare": 300.0}] * 3
    )
    return pd.DataFrame(rows)


class TestUniformIncreaseGolden:
    def test_perfect_fit(self) -> None:
        result = hedonic_time_dummy(
            _uniform_increase_panel(), quality_cols=["cls"], min_r_squared=0.0
        )
        assert result.r_squared == pytest.approx(1.0, abs=1e-9)

    def test_index_matches_the_true_uniform_price_move(self) -> None:
        result = hedonic_time_dummy(
            _uniform_increase_panel(), quality_cols=["cls"], min_r_squared=0.0
        )
        assert result.index.loc[0] == pytest.approx(1.0, abs=1e-9)
        assert result.index.loc[1] == pytest.approx(1.1, abs=1e-9)

    def test_reference_period_is_exactly_one(self) -> None:
        result = hedonic_time_dummy(
            _uniform_increase_panel(), quality_cols=["cls"], min_r_squared=0.0
        )
        assert result.reference_period == 0
        assert result.index.loc[0] == 1.0

    def test_coefficient_table_has_one_row_per_regressor(self) -> None:
        result = hedonic_time_dummy(
            _uniform_increase_panel(), quality_cols=["cls"], min_r_squared=0.0
        )
        terms = set(result.coefficients["term"])
        assert terms == {"const", "period_1", "cls_eco"}
        assert set(result.coefficients.columns) == {"term", "coefficient", "std_err", "p_value"}


class TestCompositionShiftGolden:
    """The case that motivates hedonic adjustment in the first place."""

    def test_naive_mean_price_would_show_a_spurious_67_percent_increase(self) -> None:
        panel = _composition_shift_panel()
        mean0 = panel.loc[panel["period"] == 0, "total_fare"].mean()
        mean1 = panel.loc[panel["period"] == 1, "total_fare"].mean()
        assert mean0 == pytest.approx(150.0)
        assert mean1 == pytest.approx(250.0)

    def test_hedonic_index_correctly_reports_no_price_change(self) -> None:
        result = hedonic_time_dummy(
            _composition_shift_panel(), quality_cols=["cls"], min_r_squared=0.0
        )
        assert result.r_squared == pytest.approx(1.0, abs=1e-9)
        assert result.index.loc[1] == pytest.approx(1.0, abs=1e-8)


class TestQualityFloor:
    def test_refuses_to_publish_below_the_floor(self) -> None:
        # Same shape as the composition-shift panel, but with within-cell noise so the
        # regression no longer fits perfectly. R^2 will be well below 1.
        noisy = pd.DataFrame(
            [
                {"period": 0, "cls": "eco", "total_fare": 90.0},
                {"period": 0, "cls": "eco", "total_fare": 130.0},
                {"period": 0, "cls": "eco", "total_fare": 70.0},
                {"period": 0, "cls": "biz", "total_fare": 340.0},
                {"period": 1, "cls": "eco", "total_fare": 60.0},
                {"period": 1, "cls": "biz", "total_fare": 260.0},
                {"period": 1, "cls": "biz", "total_fare": 330.0},
                {"period": 1, "cls": "biz", "total_fare": 190.0},
            ]
        )
        with pytest.raises(HedonicQualityFloorError, match="below the"):
            hedonic_time_dummy(noisy, quality_cols=["cls"], min_r_squared=0.999)

    def test_the_exception_carries_the_full_diagnostics(self) -> None:
        noisy = pd.DataFrame(
            [
                {"period": 0, "cls": "eco", "total_fare": 90.0},
                {"period": 0, "cls": "eco", "total_fare": 130.0},
                {"period": 0, "cls": "eco", "total_fare": 70.0},
                {"period": 0, "cls": "biz", "total_fare": 340.0},
                {"period": 1, "cls": "eco", "total_fare": 60.0},
                {"period": 1, "cls": "biz", "total_fare": 260.0},
                {"period": 1, "cls": "biz", "total_fare": 330.0},
                {"period": 1, "cls": "biz", "total_fare": 190.0},
            ]
        )
        with pytest.raises(HedonicQualityFloorError) as exc_info:
            hedonic_time_dummy(noisy, quality_cols=["cls"], min_r_squared=0.999)
        assert exc_info.value.result.r_squared < 0.999
        assert exc_info.value.min_r_squared == 0.999
        assert not exc_info.value.result.coefficients.empty

    def test_a_perfect_fit_always_clears_the_floor(self) -> None:
        result = hedonic_time_dummy(
            _uniform_increase_panel(), quality_cols=["cls"], min_r_squared=0.99
        )
        assert result.r_squared == pytest.approx(1.0, abs=1e-9)


class TestValidation:
    def test_requires_at_least_two_periods(self) -> None:
        panel = pd.DataFrame(
            {"period": [0, 0], "cls": ["eco", "biz"], "total_fare": [100.0, 300.0]}
        )
        with pytest.raises(ValueError, match="at least two distinct periods"):
            hedonic_time_dummy(panel, quality_cols=["cls"], min_r_squared=0.0)

    def test_rejects_non_positive_prices(self) -> None:
        panel = pd.DataFrame({"period": [0, 1], "cls": ["eco", "eco"], "total_fare": [100.0, -5.0]})
        with pytest.raises(ValueError, match="positive"):
            hedonic_time_dummy(panel, quality_cols=["cls"], min_r_squared=0.0)

    def test_missing_quality_column_is_rejected(self) -> None:
        panel = pd.DataFrame({"period": [0, 1], "total_fare": [100.0, 110.0]})
        with pytest.raises(ValueError, match="missing required columns"):
            hedonic_time_dummy(panel, quality_cols=["stops"], min_r_squared=0.0)

    def test_numeric_quality_column_enters_as_a_continuous_regressor(self) -> None:
        panel = pd.DataFrame(
            {
                "period": [0, 0, 0, 1, 1, 1],
                "stops": [0, 1, 2, 0, 1, 2],
                "total_fare": [100.0, 90.0, 80.0, 110.0, 99.0, 88.0],
            }
        )
        result = hedonic_time_dummy(panel, quality_cols=["stops"], min_r_squared=0.0)
        assert result.index.loc[1] == pytest.approx(1.1, abs=1e-6)

    def test_empty_dataframe_rejected(self) -> None:
        panel = pd.DataFrame(columns=["period", "cls", "total_fare"])
        with pytest.raises(ValueError, match="at least one observation"):
            hedonic_time_dummy(panel, quality_cols=["cls"], min_r_squared=0.0)

    def test_reference_period_not_in_the_data_is_rejected(self) -> None:
        panel = pd.DataFrame(
            {"period": [0, 1], "cls": ["eco", "eco"], "total_fare": [100.0, 110.0]}
        )
        with pytest.raises(ValueError, match="reference_period"):
            hedonic_time_dummy(panel, quality_cols=["cls"], min_r_squared=0.0, reference_period=99)

    def test_rank_deficient_design_is_rejected(self) -> None:
        """Two observations can't separate a time effect from a quality effect when
        each period only ever shows one quality category.
        """
        panel = pd.DataFrame(
            {"period": [0, 1], "cls": ["eco", "biz"], "total_fare": [100.0, 110.0]}
        )
        with pytest.raises(ValueError, match="rank-deficient"):
            hedonic_time_dummy(panel, quality_cols=["cls"], min_r_squared=0.0)
