"""The CPI bridge model: fits, reports diagnostics, predicts an interval — and never
on data that wasn't available yet.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from apix_core.config.nowcast import BridgeModelConfig, BridgeModelKind
from apix_core.nowcast.bridge import (
    InsufficientHistoryError,
    build_design_matrix,
    fit_bridge_model,
)
from apix_core.nowcast.vintage import VintageViolationError


def _spec(**overrides: object) -> BridgeModelConfig:
    payload: dict[str, object] = {
        "kind": BridgeModelKind.OLS_LAGGED,
        "n_apix_lags": 1,
        "n_cpi_lags": 1,
        "min_observations": 8,
        "ci_level": 0.95,
    }
    payload.update(overrides)
    return BridgeModelConfig.model_validate(payload)


def _synthetic_observations(n_periods: int = 30, seed: int = 7) -> pd.DataFrame:
    """A monthly series where CPI genuinely responds to lagged APIx, plus noise, so a
    fit against it should recover a non-trivial, statistically sensible coefficient —
    not just "does it run", but "does it fit something real".
    """
    rng = np.random.default_rng(seed)
    periods = pd.period_range("2023-01", periods=n_periods, freq="M")
    d_ln_apix = rng.normal(0.0, 0.02, size=n_periods)
    apix_level = 100.0 * np.exp(np.cumsum(d_ln_apix))

    d_ln_cpi = np.empty(n_periods)
    d_ln_cpi[0] = 0.0
    for t in range(1, n_periods):
        d_ln_cpi[t] = 0.5 * d_ln_apix[t] + 0.2 * d_ln_apix[t - 1] + rng.normal(0.0, 0.002)
    cpi_level = 100.0 * np.exp(np.cumsum(d_ln_cpi))

    period_dates = [p.to_timestamp().date() for p in periods]
    # CPI for a given month is only known with roughly a one-month publication lag;
    # APIx for a given month is known immediately at month end.
    collected_at = [datetime(d.year, d.month, 28, tzinfo=UTC) for d in period_dates]
    return pd.DataFrame(
        {
            "period": period_dates,
            "apix_value": apix_level,
            "cpi_value": cpi_level,
            "collected_at": collected_at,
        }
    )


class TestBuildDesignMatrix:
    def test_drops_rows_without_a_complete_lag_structure(self) -> None:
        obs = _synthetic_observations(n_periods=10)
        design = build_design_matrix(obs, _spec())
        # lag 1 on both apix and cpi diffs costs the first two periods
        assert len(design) == len(obs) - 2

    def test_row_collected_at_is_the_latest_dependency(self) -> None:
        obs = _synthetic_observations(n_periods=10)
        design = build_design_matrix(obs, _spec())
        assert (design["collected_at"] <= obs["collected_at"].max()).all()

    def test_missing_columns_is_a_value_error(self) -> None:
        with pytest.raises(ValueError, match="missing required columns"):
            build_design_matrix(pd.DataFrame({"period": [date(2026, 1, 1)]}), _spec())


class TestFitBridgeModel:
    def test_recovers_a_sensible_fit_on_synthetic_data(self) -> None:
        obs = _synthetic_observations(n_periods=36)
        target_period = date(2026, 1, 1)
        as_of = date(2026, 1, 20)
        # Append the target period: apix known (partial-month), cpi not yet published.
        obs = pd.concat(
            [
                obs,
                pd.DataFrame(
                    [
                        {
                            "period": target_period,
                            "apix_value": float(obs["apix_value"].iloc[-1]) * 1.01,
                            "cpi_value": np.nan,
                            "collected_at": datetime(2026, 1, 20, tzinfo=UTC),
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        result = fit_bridge_model(
            obs, _spec(min_observations=8), target_period, as_of, model_version="test-1"
        )
        assert result.n_obs >= 8
        assert 0.0 <= result.r_squared <= 1.0
        assert result.ci_low <= result.point_estimate <= result.ci_high
        names = [c.name for c in result.coefficients]
        assert names == ["const", "d_ln_apix_lag0", "d_ln_apix_lag1", "d_ln_cpi_lag1"]
        # The synthetic generator makes CPI genuinely depend on contemporaneous APIx
        # with a positive coefficient — the fit should recover the right sign.
        d_ln_apix_lag0 = next(c for c in result.coefficients if c.name == "d_ln_apix_lag0")
        assert d_ln_apix_lag0.estimate > 0

    def test_raises_insufficient_history_below_min_observations(self) -> None:
        obs = _synthetic_observations(n_periods=6)
        target_period = date(obs["period"].iloc[-1].year, obs["period"].iloc[-1].month, 1)
        with pytest.raises(InsufficientHistoryError):
            fit_bridge_model(
                obs, _spec(min_observations=8), target_period, date(2026, 1, 1), "test-1"
            )

    def test_midas_is_not_implemented(self) -> None:
        obs = _synthetic_observations(n_periods=12)
        target_period = date(obs["period"].iloc[-1].year, obs["period"].iloc[-1].month, 1)
        with pytest.raises(NotImplementedError, match="MIDAS"):
            fit_bridge_model(
                obs,
                _spec(kind=BridgeModelKind.MIDAS, min_observations=8),
                target_period,
                date(2026, 1, 1),
                "test-1",
            )

    def test_the_required_look_ahead_test(self) -> None:
        """A training row depending on any observation collected after as_of must
        raise, never fit silently. This is the DONE-WHEN gate from CLAUDE.md /
        the task spec: "Look-ahead bias is the failure mode that would discredit the
        whole project."
        """
        obs = _synthetic_observations(n_periods=20)
        # Poison one historical row: mark it as collected in the future relative to
        # an as_of that otherwise sits after every other row.
        obs.loc[5, "collected_at"] = datetime(2099, 1, 1, tzinfo=UTC)
        target_period = date(obs["period"].iloc[-1].year, obs["period"].iloc[-1].month, 1)
        as_of = date(2026, 1, 1)
        with pytest.raises(VintageViolationError):
            fit_bridge_model(obs, _spec(min_observations=8), target_period, as_of, "test-1")
