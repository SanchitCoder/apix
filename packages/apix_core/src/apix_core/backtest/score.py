"""Scoring APIx against a published reference fare series (DGCA monthly average
fares, once loaded — see docs/data-sources.md).

Pure function, no I/O: takes two aligned period-indexed series, returns a score. A
reference series with too little overlapping history is not padded, estimated or
guessed at — it is reported as ``n_periods=0`` (or below
``min_periods_for_correlation``) with an honest ``coverage_note``, exactly the "empty
results are data, not gaps" principle :func:`apix_core.index.aggregate.national_index`
already applies to an unweighted route.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd


@dataclass(frozen=True)
class BacktestScore:
    """Score of ``apix_series`` against ``reference_series`` over their overlap."""

    scope: str  # a route_code, or "national"
    n_periods: int
    period_from: object | None
    period_to: object | None
    correlation: float | None
    mape: float | None
    directional_accuracy: float | None
    coverage_note: str


def score_apix_vs_dgca(
    apix_series: pd.Series, reference_series: pd.Series, min_periods: int, scope: str = "national"
) -> BacktestScore:
    """Correlation, mean absolute percentage error and directional accuracy of
    ``apix_series`` against ``reference_series`` over their overlapping periods.

    Both series must be indexed by period (any sortable, comparable index — a
    ``date``, a ``pandas.Period``, ...). Only periods present and non-null in *both*
    series are scored — a period APIx published but the reference has not (yet) is not
    counted, and vice versa. Fewer than ``min_periods`` overlapping periods gives a
    :class:`BacktestScore` with every metric ``None`` and a ``coverage_note``
    explaining why — never a correlation computed on too little evidence to mean
    anything.
    """
    if min_periods < 2:
        raise ValueError("score_apix_vs_dgca: min_periods must be at least 2")

    aligned = (
        apix_series.rename("apix")
        .to_frame()
        .join(reference_series.rename("reference"), how="inner")
    )
    aligned = aligned.dropna()
    n_periods = len(aligned)

    if n_periods == 0:
        return BacktestScore(
            scope=scope,
            n_periods=0,
            period_from=None,
            period_to=None,
            correlation=None,
            mape=None,
            directional_accuracy=None,
            coverage_note="no overlapping periods between apix_series and reference_series",
        )
    if n_periods < min_periods:
        return BacktestScore(
            scope=scope,
            n_periods=n_periods,
            period_from=aligned.index.min(),
            period_to=aligned.index.max(),
            correlation=None,
            mape=None,
            directional_accuracy=None,
            coverage_note=(
                f"only {n_periods} overlapping period(s); min_periods requires {min_periods}"
            ),
        )

    apix = aligned["apix"].to_numpy(dtype=np.float64)
    reference = aligned["reference"].to_numpy(dtype=np.float64)

    correlation = (
        float(np.corrcoef(apix, reference)[0, 1])
        if np.std(apix) > 0 and np.std(reference) > 0
        else None
    )
    mape = float(np.mean(np.abs((apix - reference) / reference)) * 100.0)

    directional_accuracy: float | None = None
    if n_periods >= 2:
        apix_moves = np.sign(np.diff(apix))
        reference_moves = np.sign(np.diff(reference))
        comparable = reference_moves != 0
        if comparable.any():
            directional_accuracy = float(
                np.mean(apix_moves[comparable] == reference_moves[comparable]) * 100.0
            )

    return BacktestScore(
        scope=scope,
        n_periods=n_periods,
        period_from=aligned.index.min(),
        period_to=aligned.index.max(),
        correlation=correlation,
        mape=mape,
        directional_accuracy=directional_accuracy,
        coverage_note=f"{n_periods} overlapping period(s) scored",
    )


def score_national_and_per_route(
    apix_national: pd.Series,
    reference_national: pd.Series,
    apix_by_route: dict[str, pd.Series],
    reference_by_route: dict[str, pd.Series],
    min_periods: int,
) -> list[BacktestScore]:
    """The national score, plus one score per route present in both
    ``apix_by_route`` and ``reference_by_route`` — routes present in only one are
    silently skipped from the per-route list (not scoreable, not an error) but do not
    affect the national score, which is computed independently.
    """
    scores = [score_apix_vs_dgca(apix_national, reference_national, min_periods, scope="national")]
    common_routes = sorted(set(apix_by_route) & set(reference_by_route))
    for route in common_routes:
        scores.append(
            score_apix_vs_dgca(
                apix_by_route[route], reference_by_route[route], min_periods, scope=route
            )
        )
    return scores


__all__ = ["BacktestScore", "score_apix_vs_dgca", "score_national_and_per_route"]
