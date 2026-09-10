"""Quality adjustment: the time-dummy hedonic method.

An elementary aggregate (:mod:`apix_core.index.elementary`) compares matched products —
implicitly assuming that what changed between periods was price and nothing else. A
time-dummy hedonic regression relaxes that: it regresses log price on time dummies
*and* a vector of quality characteristics (stops, departure time, carrier, ...), so the
time-dummy coefficients are the price movement with quality composition held constant.
This is what lets the index stay valid even when the mix of what is actually flown
shifts (more non-stop flights this month, a different carrier mix, and so on).

Refuses to publish outright if the regression's R-squared falls below the configured
floor (``config/method.yaml``: ``quality_adjustment.min_r_squared``) — CLAUDE.md
principle 2: a hedonic fit too weak to trust is a recorded failure, not a quietly
published number.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm

_REQUIRED_COLUMNS = ("period", "total_fare")


@dataclass(frozen=True)
class HedonicResult:
    """Output of :func:`hedonic_time_dummy`.

    ``index`` is indexed by period, normalised to exactly 1.0 at the reference period.
    ``coefficients`` has one row per regressor: ``term``, ``coefficient``, ``std_err``,
    ``p_value`` — the full diagnostic table CLAUDE.md and the task require, not just
    the headline numbers.
    """

    index: pd.Series
    r_squared: float
    coefficients: pd.DataFrame
    n_obs: int
    n_periods: int
    reference_period: object


class HedonicQualityFloorError(RuntimeError):
    """The hedonic fit is too weak to publish.

    Carries the full :class:`HedonicResult` so the reason is recorded, not discarded —
    a caller that catches this can still log or store the diagnostics that led to the
    refusal.
    """

    def __init__(self, result: HedonicResult, min_r_squared: float) -> None:
        super().__init__(
            f"hedonic time-dummy R-squared {result.r_squared:.4f} is below the "
            f"configured floor {min_r_squared:.4f} "
            f"({result.n_obs} observations, {result.n_periods} periods) — refusing to publish"
        )
        self.result = result
        self.min_r_squared = min_r_squared


def _design_matrix(
    df: pd.DataFrame, quality_cols: Sequence[str], reference_period: object
) -> pd.DataFrame:
    period_str = df["period"].astype(str)
    ref_str = str(reference_period)
    time_dummies = pd.get_dummies(period_str, prefix="period", dtype=float)
    ref_col = f"period_{ref_str}"
    if ref_col not in time_dummies.columns:
        raise ValueError(f"reference_period {reference_period!r} is not present in the data")
    time_dummies = time_dummies.drop(columns=[ref_col])

    quality_parts: list[pd.DataFrame] = []
    for col in quality_cols:
        series = df[col]
        if pd.api.types.is_numeric_dtype(series):
            quality_parts.append(series.astype(float).rename(col).to_frame())
        else:
            quality_parts.append(
                pd.get_dummies(series.astype(str), prefix=col, drop_first=True, dtype=float)
            )
    quality = (
        pd.concat(quality_parts, axis=1)
        if quality_parts
        else pd.DataFrame(index=df.index, dtype=float)
    )
    design = pd.concat([time_dummies, quality], axis=1)
    design.insert(0, "const", 1.0)
    return design


def hedonic_time_dummy(
    df: pd.DataFrame,
    quality_cols: Sequence[str],
    min_r_squared: float,
    reference_period: object | None = None,
) -> HedonicResult:
    r"""Time-dummy hedonic quality-adjusted index.

    :math:`\ln(\text{total\_fare}) = \alpha + \sum_{t \neq 0} \delta_t D_t +
    \boldsymbol{\beta}^\top \mathbf{x} + \varepsilon`

    ``df`` needs a ``period`` column and a ``total_fare`` column, plus every column
    named in ``quality_cols``. Numeric quality columns enter as continuous regressors;
    non-numeric ones are one-hot encoded (first category dropped, to avoid the dummy
    trap). The reference period (default: the earliest) is held out of the time-dummy
    set, so ``index[reference_period] == 1.0`` exactly; every other period's index
    value is :math:`\exp(\delta_t)`.

    Raises :class:`HedonicQualityFloorError` — carrying the full result — if the
    fitted R-squared is below ``min_r_squared``.
    """
    missing = [c for c in (*_REQUIRED_COLUMNS, *quality_cols) if c not in df.columns]
    if missing:
        raise ValueError(f"hedonic_time_dummy: missing required columns: {missing}")
    if df.empty:
        raise ValueError("hedonic_time_dummy requires at least one observation")
    if (df["total_fare"] <= 0).any():
        raise ValueError("hedonic_time_dummy requires strictly positive total_fare")
    periods = sorted(df["period"].unique())
    if len(periods) < 2:
        raise ValueError("hedonic_time_dummy requires at least two distinct periods")
    ref = periods[0] if reference_period is None else reference_period

    design = _design_matrix(df, quality_cols, ref)
    y = np.log(df["total_fare"].to_numpy(dtype=np.float64))

    rank = np.linalg.matrix_rank(design.to_numpy(dtype=np.float64))
    if rank < design.shape[1]:
        raise ValueError(
            "the hedonic design matrix is rank-deficient — too few observations or "
            "collinear quality characteristics for this period/quality combination"
        )

    model = sm.OLS(y, design).fit()

    coefficients = pd.DataFrame(
        {
            "term": model.params.index,
            "coefficient": model.params.to_numpy(),
            "std_err": model.bse.to_numpy(),
            "p_value": model.pvalues.to_numpy(),
        }
    ).reset_index(drop=True)

    time_dummy_terms = {p: f"period_{p}" for p in periods if p != ref}
    levels = {ref: 1.0}
    for period, term in time_dummy_terms.items():
        coefficient = float(model.params[term])
        levels[period] = float(np.exp(coefficient))
    index = pd.Series(levels, name="hedonic_time_dummy").reindex(periods)
    index.index.name = "period"

    result = HedonicResult(
        index=index,
        r_squared=float(model.rsquared),
        coefficients=coefficients,
        n_obs=int(model.nobs),
        n_periods=len(periods),
        reference_period=ref,
    )
    if result.r_squared < min_r_squared:
        raise HedonicQualityFloorError(result, min_r_squared)
    return result


__all__ = ["HedonicQualityFloorError", "HedonicResult", "hedonic_time_dummy"]
