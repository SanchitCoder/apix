r"""ATF (aviation turbine fuel) price pass-through.

A distributed-lag regression of fare movement on lagged ATF price movement:

.. math::

    \Delta\ln\text{fare}_t = \alpha + \sum_{l=0}^{L} \beta_l \Delta\ln\text{ATF}_{t-l}
        + \varepsilon_t

``lag_chart_data`` turns the fitted :math:`\beta_l` into the tidy shape a
distributed-lag chart needs (per-lag and cumulative pass-through); rendering is a
``docs/``-level script, same split as :mod:`apix_core.testing.synthetic` versus
``docs/plot_synthetic_curves.py``.

No real ATF price series exists in this repository yet — see docs/data-sources.md.
:func:`fit_atf_passthrough` is a pure function over whatever ``observations`` it is
given; it does not know or care whether the ATF prices came from a real loaded extract
or a test fixture. It also respects vintage discipline like the CPI bridge model: pass
``as_of`` and every row is checked against
:func:`apix_core.nowcast.vintage.assert_no_look_ahead` before fitting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import statsmodels.api as sm

from apix_core.nowcast.bridge import CoefficientEstimate
from apix_core.nowcast.vintage import assert_no_look_ahead

if TYPE_CHECKING:
    from datetime import date

    from apix_core.config.nowcast import AtfPassThroughConfig

REQUIRED_OBSERVATION_COLUMNS = ("period", "fare_value", "atf_price", "collected_at")


@dataclass(frozen=True)
class DistributedLagResult:
    """Output of :func:`fit_atf_passthrough`."""

    model_version: str
    max_lag: int
    coefficients: tuple[CoefficientEstimate, ...]
    n_obs: int
    r_squared: float
    # Sum of the lag coefficients (excluding the intercept): the total fraction of an
    # ATF price move that has passed through to fares by lag L.
    cumulative_passthrough: float
    design_matrix: pd.DataFrame


class InsufficientHistoryError(RuntimeError):
    """Too few usable observations to fit the distributed lag."""

    def __init__(self, n_available: int, n_required: int) -> None:
        super().__init__(
            f"only {n_available} usable observation(s) after building the lag "
            f"structure; AtfPassThroughConfig.min_observations requires {n_required} "
            f"— refusing to fit"
        )
        self.n_available = n_available
        self.n_required = n_required


def _feature_cols(max_lag: int) -> list[str]:
    return [f"d_ln_atf_lag{lag}" for lag in range(max_lag + 1)]


def build_design_matrix(observations: pd.DataFrame, spec: AtfPassThroughConfig) -> pd.DataFrame:
    """One row per period with a complete ATF lag structure and a fare target.

    Mirrors :func:`apix_core.nowcast.bridge.build_design_matrix`'s shape: every
    returned row carries ``collected_at`` = the latest timestamp any value it depends
    on became known, ready for :func:`apix_core.nowcast.vintage.assert_no_look_ahead`.
    """
    missing = [c for c in REQUIRED_OBSERVATION_COLUMNS if c not in observations.columns]
    if missing:
        raise ValueError(f"atf_passthrough: observations missing required columns: {missing}")
    if observations.empty:
        raise ValueError("atf_passthrough: observations must have at least one row")
    if observations["period"].duplicated().any():
        raise ValueError("atf_passthrough: observations must have one row per period")

    df = observations.sort_values("period").reset_index(drop=True)
    if (df["fare_value"] <= 0).any():
        raise ValueError("atf_passthrough: fare_value must be strictly positive")
    if (df["atf_price"] <= 0).any():
        raise ValueError("atf_passthrough: atf_price must be strictly positive")

    df["target"] = np.log(df["fare_value"].to_numpy(dtype=np.float64))
    df["target"] = df["target"].diff()
    df["_d_ln_atf"] = np.log(df["atf_price"].to_numpy(dtype=np.float64))
    df["_d_ln_atf"] = df["_d_ln_atf"].diff()

    for lag in range(spec.max_lag + 1):
        df[f"d_ln_atf_lag{lag}"] = df["_d_ln_atf"].shift(lag)

    collected_shifts = pd.concat(
        [df["collected_at"].shift(lag) for lag in range(spec.max_lag + 1)], axis=1
    )
    df["collected_at"] = collected_shifts.max(axis=1)

    feature_cols = _feature_cols(spec.max_lag)
    keep = ["period", *feature_cols, "target", "collected_at"]
    return df[keep].dropna(subset=[*feature_cols, "target", "collected_at"]).reset_index(drop=True)


def fit_atf_passthrough(
    observations: pd.DataFrame,
    spec: AtfPassThroughConfig,
    model_version: str,
    as_of: date | None = None,
) -> DistributedLagResult:
    """Fit the ATF-price -> fare distributed-lag regression.

    ``as_of``, if given, is enforced with the same vintage guard the CPI bridge model
    uses — an ATF pass-through estimate is just as capable of look-ahead bias as the
    bridge model, and CLAUDE.md draws no distinction between the two.
    """
    training = build_design_matrix(observations, spec)
    if as_of is not None:
        assert_no_look_ahead(training, as_of)
    if len(training) < spec.min_observations:
        raise InsufficientHistoryError(len(training), spec.min_observations)

    feature_cols = _feature_cols(spec.max_lag)
    column_names = ["const", *feature_cols]
    x = np.column_stack([np.ones(len(training)), training[feature_cols].to_numpy(dtype=np.float64)])
    y = training["target"].to_numpy(dtype=np.float64)
    model = sm.OLS(y, x).fit()

    coefficients = tuple(
        CoefficientEstimate(
            name=name,
            estimate=float(model.params[i]),
            std_error=float(model.bse[i]),
            t_stat=float(model.tvalues[i]),
            p_value=float(model.pvalues[i]),
        )
        for i, name in enumerate(column_names)
    )
    cumulative_passthrough = float(sum(c.estimate for c in coefficients if c.name != "const"))

    return DistributedLagResult(
        model_version=model_version,
        max_lag=spec.max_lag,
        coefficients=coefficients,
        n_obs=int(model.nobs),
        r_squared=float(model.rsquared),
        cumulative_passthrough=cumulative_passthrough,
        design_matrix=training,
    )


def lag_chart_data(result: DistributedLagResult) -> pd.DataFrame:
    """Tidy per-lag and cumulative pass-through, ready for a distributed-lag chart.

    Data only — no plotting here (see ``docs/plot_synthetic_curves.py`` for the split
    this repo already uses between data-shaping and rendering).
    """
    rows = [c for c in result.coefficients if c.name != "const"]
    lags = [int(c.name.removeprefix("d_ln_atf_lag")) for c in rows]
    coefficients = [c.estimate for c in rows]
    std_errors = [c.std_error for c in rows]
    order = np.argsort(lags)
    lags_sorted = [lags[i] for i in order]
    coefficients_sorted = [coefficients[i] for i in order]
    std_errors_sorted = [std_errors[i] for i in order]
    return pd.DataFrame(
        {
            "lag": lags_sorted,
            "coefficient": coefficients_sorted,
            "std_error": std_errors_sorted,
            "cumulative_coefficient": np.cumsum(coefficients_sorted),
        }
    )


__all__ = [
    "REQUIRED_OBSERVATION_COLUMNS",
    "DistributedLagResult",
    "InsufficientHistoryError",
    "build_design_matrix",
    "fit_atf_passthrough",
    "lag_chart_data",
]
