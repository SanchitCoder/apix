"""ATF pass-through: a distributed lag that recovers a known cumulative effect on
synthetic data, and respects vintage discipline like every other nowcast fit.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from apix_core.config.nowcast import AtfPassThroughConfig
from apix_core.nowcast.atf_passthrough import (
    InsufficientHistoryError,
    build_design_matrix,
    fit_atf_passthrough,
    lag_chart_data,
)
from apix_core.nowcast.vintage import VintageViolationError


def _spec(**overrides: object) -> AtfPassThroughConfig:
    payload: dict[str, object] = {"max_lag": 2, "min_observations": 8}
    payload.update(overrides)
    return AtfPassThroughConfig.model_validate(payload)


def _synthetic_observations(n_periods: int = 30, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    periods = pd.period_range("2023-01", periods=n_periods, freq="M")
    d_ln_atf = rng.normal(0.0, 0.03, size=n_periods)
    atf_price = 60000.0 * np.exp(np.cumsum(d_ln_atf))

    # Pass-through of 0.3 at lag 0, 0.15 at lag 1, 0.05 at lag 2 — cumulative 0.5.
    d_ln_fare = np.empty(n_periods)
    d_ln_fare[:] = 0.0
    for t in range(n_periods):
        val = 0.3 * d_ln_atf[t]
        if t >= 1:
            val += 0.15 * d_ln_atf[t - 1]
        if t >= 2:
            val += 0.05 * d_ln_atf[t - 2]
        d_ln_fare[t] = val + rng.normal(0.0, 0.001)
    fare_value = 5000.0 * np.exp(np.cumsum(d_ln_fare))

    period_dates = [p.to_timestamp().date() for p in periods]
    collected_at = [datetime(d.year, d.month, 28, tzinfo=UTC) for d in period_dates]
    return pd.DataFrame(
        {
            "period": period_dates,
            "fare_value": fare_value,
            "atf_price": atf_price,
            "collected_at": collected_at,
        }
    )


class TestBuildDesignMatrix:
    def test_drops_rows_without_a_complete_lag_structure(self) -> None:
        obs = _synthetic_observations(n_periods=12)
        design = build_design_matrix(obs, _spec(max_lag=2))
        # one row lost to the target/lag0 diff, plus one per additional lag
        assert len(design) == len(obs) - 3

    def test_missing_columns_is_a_value_error(self) -> None:
        with pytest.raises(ValueError, match="missing required columns"):
            build_design_matrix(pd.DataFrame({"period": []}), _spec())


class TestFitAtfPassthrough:
    def test_recovers_the_known_cumulative_passthrough(self) -> None:
        obs = _synthetic_observations(n_periods=36)
        result = fit_atf_passthrough(obs, _spec(max_lag=2, min_observations=8), "test-1")
        assert result.n_obs >= 8
        assert result.cumulative_passthrough == pytest.approx(0.5, abs=0.05)

    def test_raises_insufficient_history(self) -> None:
        obs = _synthetic_observations(n_periods=5)
        with pytest.raises(InsufficientHistoryError):
            fit_atf_passthrough(obs, _spec(max_lag=2, min_observations=8), "test-1")

    def test_look_ahead_guard_when_as_of_is_given(self) -> None:
        obs = _synthetic_observations(n_periods=20)
        obs.loc[5, "collected_at"] = datetime(2099, 1, 1, tzinfo=UTC)
        with pytest.raises(VintageViolationError):
            fit_atf_passthrough(
                obs,
                _spec(max_lag=2, min_observations=8),
                "test-1",
                as_of=obs["period"].iloc[-1],
            )


class TestLagChartData:
    def test_lags_are_ordered_and_cumulative_matches_the_result(self) -> None:
        obs = _synthetic_observations(n_periods=36)
        result = fit_atf_passthrough(obs, _spec(max_lag=2, min_observations=8), "test-1")
        chart = lag_chart_data(result)
        assert list(chart["lag"]) == [0, 1, 2]
        assert chart["cumulative_coefficient"].iloc[-1] == pytest.approx(
            result.cumulative_passthrough
        )
