r"""The CPI air-fare bridge model.

Phase 1: an aggregated-regressor OLS with lags, not MIDAS — true mixed-frequency
estimation needs scaffolding this repo does not have yet
(see docs/adr/0004-ols-lagged-bridge-over-midas.md). The functional form:

.. math::

    \Delta\ln\text{CPI}_t = \alpha + \sum_{l=0}^{L_x} \beta_l \Delta\ln\text{APIx}_{t-l}
        + \sum_{l=1}^{L_y} \gamma_l \Delta\ln\text{CPI}_{t-l} + \varepsilon_t

``APIx_t`` (lag 0, the "aggregated regressor") is whatever the caller supplies as that
period's ``apix_value`` — for the not-yet-closed target period this is a partial-month
aggregate built from whatever window data exists as of the nowcast date; for closed
periods it is the published headline monthly index. This module does not distinguish
the two cases; it is the caller's responsibility to have built the partial-month figure
correctly. Every fit passes through :func:`apix_core.nowcast.vintage.assert_no_look_ahead`
first — see that module for why there is no separate "vintage store" table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.stattools import durbin_watson, jarque_bera

from apix_core.config.nowcast import BridgeModelConfig, BridgeModelKind, RobustCovType
from apix_core.nowcast.vintage import assert_no_look_ahead

if TYPE_CHECKING:
    from datetime import date

REQUIRED_OBSERVATION_COLUMNS = ("period", "apix_value", "cpi_value", "collected_at")


@dataclass(frozen=True)
class CoefficientEstimate:
    """One regressor's estimate, standard error and significance."""

    name: str
    estimate: float
    std_error: float
    t_stat: float
    p_value: float


@dataclass(frozen=True)
class BridgeModelResult:
    """Output of :func:`fit_bridge_model` — coefficients, diagnostics, and a
    prediction interval for the target period's CPI air-fare item index level.
    """

    model_version: str
    target_period: date
    as_of: date
    coefficients: tuple[CoefficientEstimate, ...]
    n_obs: int
    r_squared: float
    adj_r_squared: float
    residual_std_error: float
    durbin_watson: float
    jarque_bera_pvalue: float
    point_estimate: float
    ci_low: float
    ci_high: float
    ci_level: float
    # The training design matrix actually fitted on — kept for audit: every coefficient
    # traces back to exactly these rows (CLAUDE.md principle 1).
    design_matrix: pd.DataFrame


class InsufficientHistoryError(RuntimeError):
    """Too few usable observations to fit — refuses rather than returning a fit
    nobody could trust (the same refusal pattern as
    :class:`apix_core.index.hedonic.HedonicQualityFloorError`).
    """

    def __init__(self, n_available: int, n_required: int) -> None:
        super().__init__(
            f"only {n_available} usable observation(s) after building the lag "
            f"structure; BridgeModelConfig.min_observations requires {n_required} "
            f"— refusing to fit"
        )
        self.n_available = n_available
        self.n_required = n_required


def _feature_cols(spec: BridgeModelConfig) -> list[str]:
    apix_cols = [f"d_ln_apix_lag{lag}" for lag in range(spec.n_apix_lags + 1)]
    cpi_cols = [f"d_ln_cpi_lag{lag}" for lag in range(1, spec.n_cpi_lags + 1)]
    return apix_cols + cpi_cols


def _build_lagged_frame(observations: pd.DataFrame, spec: BridgeModelConfig) -> pd.DataFrame:
    """One row per period with the lag structure ``spec`` needs, ``target`` (this
    period's Δln CPI, null where CPI is not yet published) and ``collected_at`` (the
    latest timestamp any value the row depends on — including the target — became
    known). Rows are not yet dropped for missing lags or a missing target; callers
    select the training subset (target non-null) or the prediction row (target null)
    from this same frame, so both use identical lag construction.
    """
    missing = [c for c in REQUIRED_OBSERVATION_COLUMNS if c not in observations.columns]
    if missing:
        raise ValueError(f"nowcast bridge: observations missing required columns: {missing}")
    if observations.empty:
        raise ValueError("nowcast bridge: observations must have at least one row")
    if observations["period"].duplicated().any():
        raise ValueError("nowcast bridge: observations must have one row per period")

    df = observations.sort_values("period").reset_index(drop=True)
    if (df["apix_value"] <= 0).any():
        raise ValueError("nowcast bridge: apix_value must be strictly positive")
    if (df["cpi_value"].dropna() <= 0).any():
        raise ValueError("nowcast bridge: cpi_value must be strictly positive where present")

    df["_d_ln_apix"] = np.log(df["apix_value"].to_numpy(dtype=np.float64))
    df["_d_ln_apix"] = df["_d_ln_apix"].diff()
    df["_d_ln_cpi"] = np.log(df["cpi_value"].astype(float))
    df["_d_ln_cpi"] = df["_d_ln_cpi"].diff()

    for lag in range(spec.n_apix_lags + 1):
        df[f"d_ln_apix_lag{lag}"] = df["_d_ln_apix"].shift(lag)
    for lag in range(1, spec.n_cpi_lags + 1):
        df[f"d_ln_cpi_lag{lag}"] = df["_d_ln_cpi"].shift(lag)
    df["target"] = df["_d_ln_cpi"]

    used_lags = sorted({0, *range(spec.n_apix_lags + 1), *range(1, spec.n_cpi_lags + 1)})
    collected_shifts = pd.concat([df["collected_at"].shift(lag) for lag in used_lags], axis=1)
    df["collected_at"] = collected_shifts.max(axis=1)

    keep = ["period", *_feature_cols(spec), "target", "collected_at"]
    return df[keep].reset_index(drop=True)


def build_design_matrix(observations: pd.DataFrame, spec: BridgeModelConfig) -> pd.DataFrame:
    """The training rows: every period with a complete lag structure and a published
    (non-null) target. Each row's ``collected_at`` is the latest timestamp any value it
    depends on became known — pass this frame straight to
    :func:`apix_core.nowcast.vintage.assert_no_look_ahead`.
    """
    full = _build_lagged_frame(observations, spec)
    feature_cols = _feature_cols(spec)
    return full.dropna(subset=[*feature_cols, "target", "collected_at"]).reset_index(drop=True)


def fit_bridge_model(
    observations: pd.DataFrame,
    spec: BridgeModelConfig,
    target_period: date,
    as_of: date,
    model_version: str,
) -> BridgeModelResult:
    """Fit the bridge model and nowcast the CPI air-fare item index for
    ``target_period``.

    Raises :class:`NotImplementedError` if ``spec.kind`` is
    :attr:`BridgeModelKind.MIDAS` (listed in the config schema to state the growth
    path; not implemented). Raises
    :class:`apix_core.nowcast.vintage.VintageViolationError` if any training row
    depends on a value collected after ``as_of`` — this is the look-ahead guard;
    CLAUDE.md is explicit that this is the failure mode that would discredit the whole
    project. Raises :class:`InsufficientHistoryError` below
    ``spec.min_observations`` usable rows.
    """
    if spec.kind is BridgeModelKind.MIDAS:
        raise NotImplementedError(
            "MIDAS bridge models are not implemented. config/nowcast.yaml's "
            "bridge_model.kind lists 'midas' to state the growth path only — see "
            "docs/adr/0004-ols-lagged-bridge-over-midas.md. Use kind: ols_lagged."
        )

    training = build_design_matrix(observations, spec)
    assert_no_look_ahead(training, as_of)
    if len(training) < spec.min_observations:
        raise InsufficientHistoryError(len(training), spec.min_observations)

    full = _build_lagged_frame(observations, spec)
    feature_cols = _feature_cols(spec)
    target_rows = full.loc[full["period"] == target_period]
    if target_rows.empty:
        raise ValueError(f"fit_bridge_model: target_period {target_period} not in observations")
    predict_row = target_rows.iloc[0]
    if predict_row[feature_cols].isna().any():
        raise ValueError(
            f"fit_bridge_model: target_period {target_period} does not have a complete "
            f"lag structure — not enough prior history to build its regressors"
        )

    prior_known = observations.loc[
        observations["cpi_value"].notna() & (observations["period"] < target_period)
    ].sort_values("period")
    if prior_known.empty:
        raise ValueError(
            f"fit_bridge_model: no published cpi_value before target_period {target_period}"
        )
    base_level = float(prior_known["cpi_value"].iloc[-1])

    column_names = ["const", *feature_cols]
    x = np.column_stack([np.ones(len(training)), training[feature_cols].to_numpy(dtype=np.float64)])
    y = training["target"].to_numpy(dtype=np.float64)
    ols = sm.OLS(y, x).fit()
    robust = (
        ols.get_robustcov_results(cov_type="HAC", maxlags=spec.hac_maxlags)
        if spec.robust_cov is RobustCovType.HAC
        else ols.get_robustcov_results(cov_type="HC1")
    )

    coefficients = tuple(
        CoefficientEstimate(
            name=name,
            estimate=float(robust.params[i]),
            std_error=float(robust.bse[i]),
            t_stat=float(robust.tvalues[i]),
            p_value=float(robust.pvalues[i]),
        )
        for i, name in enumerate(column_names)
    )
    _jb_stat, jb_pvalue, _jb_skew, _jb_kurtosis = jarque_bera(robust.resid)

    predict_x = np.concatenate(
        [[1.0], predict_row[feature_cols].to_numpy(dtype=np.float64)]
    ).reshape(1, -1)
    prediction = robust.get_prediction(predict_x)
    frame = prediction.summary_frame(alpha=1.0 - spec.ci_level)
    point_d_ln_cpi = float(frame["mean"].iloc[0])
    ci_low_d_ln_cpi = float(frame["obs_ci_lower"].iloc[0])
    ci_high_d_ln_cpi = float(frame["obs_ci_upper"].iloc[0])

    return BridgeModelResult(
        model_version=model_version,
        target_period=target_period,
        as_of=as_of,
        coefficients=coefficients,
        n_obs=int(robust.nobs),
        r_squared=float(robust.rsquared),
        adj_r_squared=float(robust.rsquared_adj),
        residual_std_error=float(np.sqrt(robust.mse_resid)),
        durbin_watson=float(durbin_watson(robust.resid)),
        jarque_bera_pvalue=float(jb_pvalue),
        point_estimate=base_level * float(np.exp(point_d_ln_cpi)),
        ci_low=base_level * float(np.exp(ci_low_d_ln_cpi)),
        ci_high=base_level * float(np.exp(ci_high_d_ln_cpi)),
        ci_level=spec.ci_level,
        design_matrix=training,
    )


__all__ = [
    "REQUIRED_OBSERVATION_COLUMNS",
    "BridgeModelResult",
    "CoefficientEstimate",
    "InsufficientHistoryError",
    "build_design_matrix",
    "fit_bridge_model",
]
