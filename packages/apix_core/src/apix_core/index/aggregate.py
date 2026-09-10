"""The aggregation hierarchy:

    quote -> (route, advance_days) elementary index          [apix_core.index.elementary]
          -> route index, booking-profile weighted            [apix_core.index.weighting]
          -> national APIx, weighted by dgca_pax_share         [this module]

plus sub-indices at whatever breakdown a caller needs (carrier type, trunk vs
non-trunk, advance window): all of them are the same weighted roll-up, grouped by a
different column.

Every function here is a weighted *geometric* mean of an ``index_value`` column,
consistent with the log-additive framework the rest of this package uses
(:mod:`apix_core.index.elementary`, :mod:`apix_core.index.multilateral`,
:mod:`apix_core.index.weighting`). ``n_quotes`` and ``coverage_pct`` travel up with
every roll-up — CLAUDE.md: a national statistics office will not publish a number
without knowing what it rests on, at every level, not only at the bottom.

This module does not itself decide what "trunk vs non-trunk" or "carrier type" means —
it has no access to reference data (pure function, no I/O). The caller joins whatever
classification column it needs onto the elementary-level dataframe before calling
:func:`sub_index_by`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pandas as pd

VALUE_COL = "index_value"
N_QUOTES_COL = "n_quotes"
COVERAGE_COL = "coverage_pct"

_REQUIRED_COLUMNS = (VALUE_COL, N_QUOTES_COL, COVERAGE_COL)


def _validate(df: pd.DataFrame, weight_col: str) -> None:
    missing = [c for c in (*_REQUIRED_COLUMNS, weight_col) if c not in df.columns]
    if missing:
        raise ValueError(f"input is missing required columns: {missing}")
    if df.empty:
        raise ValueError("input must have at least one row")
    if (df[VALUE_COL] <= 0).any():
        raise ValueError("index_value must be strictly positive")
    if (df[N_QUOTES_COL] < 0).any():
        raise ValueError("n_quotes must be non-negative")
    if ((df[COVERAGE_COL] < 0) | (df[COVERAGE_COL] > 100)).any():
        raise ValueError("coverage_pct must be within [0, 100]")


def weighted_geometric_rollup(
    df: pd.DataFrame, group_cols: Sequence[str], weight_col: str
) -> pd.DataFrame:
    r"""Roll ``df`` up by one grouping step: a weighted geometric mean of
    ``index_value``, ``n_quotes`` summed, and ``coverage_pct`` averaged.

    :math:`I_g = \exp\left(\sum_i \tilde{w}_i \ln I_i\right)`, :math:`\tilde{w}_i =
    w_i / \sum_{j \in g} w_j` — weights renormalised within each group so an
    incomplete weight vector (a route dropped from the current window) does not bias
    the level, only shrinks the weight mass that survives.

    ``n_quotes`` sums exactly: the count of underlying observations can only grow as
    you aggregate, never shrink or get diluted.

    ``coverage_pct`` is a quotes-weighted (not aggregation-weight-weighted) average of
    the children's coverage: a heavily-weighted but sparsely-observed child must not
    be able to mask a real gap in a lightly-weighted, densely-observed one.

    ``group_cols=()`` collapses ``df`` to a single row (used by :func:`national_index`).
    """
    _validate(df, weight_col)
    work = df.copy()
    weight = work[weight_col].to_numpy(dtype=np.float64)
    if np.any(weight < 0):
        raise ValueError(f"{weight_col} must be non-negative")
    work["_log_value"] = np.log(work[VALUE_COL].to_numpy(dtype=np.float64))
    work["_weight"] = weight
    work["_quotes"] = work[N_QUOTES_COL].to_numpy(dtype=np.float64)
    work["_quotes_x_coverage"] = work["_quotes"] * work[COVERAGE_COL].to_numpy(dtype=np.float64)

    keys = list(group_cols)
    group_keys = keys if keys else ["_scope"]
    if not keys:
        work["_scope"] = "__all__"
    grouped = work.groupby(group_keys, sort=True)

    weight_sum = grouped["_weight"].transform("sum")
    if (weight_sum <= 0).any():
        raise ValueError("a group's weights sum to zero or less; cannot aggregate")
    work["_norm_weight"] = work["_weight"] / weight_sum
    work["_weighted_log_value"] = work["_norm_weight"] * work["_log_value"]

    result = work.groupby(group_keys, sort=True).agg(
        _log_index=("_weighted_log_value", "sum"),
        **{N_QUOTES_COL: (N_QUOTES_COL, "sum")},
        _quotes_sum=("_quotes", "sum"),
        _quotes_x_coverage_sum=("_quotes_x_coverage", "sum"),
    )
    result = result.reset_index()
    if not keys:
        result = result.drop(columns=["_scope"])

    result[VALUE_COL] = np.exp(result["_log_index"])
    result[COVERAGE_COL] = np.where(
        result["_quotes_sum"] > 0,
        result["_quotes_x_coverage_sum"] / result["_quotes_sum"].replace(0, np.nan),
        0.0,
    )
    return result[[*keys, VALUE_COL, N_QUOTES_COL, COVERAGE_COL]].reset_index(drop=True)


def route_index(
    elementary: pd.DataFrame, booking_profile_weights: dict[str, float]
) -> pd.DataFrame:
    """Roll (route_code, advance_window) elementary cells up to one index per route.

    ``elementary`` needs ``route_code``, ``advance_window``, ``index_value``,
    ``n_quotes``, ``coverage_pct``. Weights are the configured booking-profile
    lead-time distribution (see :mod:`apix_core.index.weighting` and
    ``config/method.yaml``'s ``booking_profile`` — a stated assumption, documented
    there, not measured).
    """
    missing = [c for c in ("route_code", "advance_window") if c not in elementary.columns]
    if missing:
        raise ValueError(f"route_index: missing required columns: {missing}")
    work = elementary.copy()
    work["_weight"] = work["advance_window"].map(booking_profile_weights)
    unweighted = sorted(work.loc[work["_weight"].isna(), "advance_window"].unique())
    if unweighted:
        raise ValueError(f"no booking-profile weight configured for windows: {unweighted}")
    return weighted_geometric_rollup(work, ["route_code"], "_weight")


def national_index(
    route_level: pd.DataFrame, dgca_pax_share: dict[str, float]
) -> tuple[pd.DataFrame, list[str]]:
    """Roll route indexes up to the single national APIx, weighted by
    ``dgca_pax_share``.

    Routes with no configured passenger-share weight are excluded from the national
    number and reported back in ``excluded_routes`` — CLAUDE.md principle 5: an
    unweighted route is a recorded gap, never an invented weight (see
    ``config/basket.yaml``, where ``dgca_pax_share`` is null until Phase 2 loads the
    real DGCA release).
    """
    if "route_code" not in route_level.columns:
        raise ValueError("national_index: route_level must have a route_code column")
    work = route_level.copy()
    work["_weight"] = work["route_code"].map(dgca_pax_share)
    excluded = sorted(work.loc[work["_weight"].isna(), "route_code"].unique())
    available = work.dropna(subset=["_weight"])
    if available.empty:
        raise ValueError(
            "no route has a configured dgca_pax_share; the national index cannot be computed"
        )
    result = weighted_geometric_rollup(available, [], "_weight")
    return result, list(excluded)


def sub_index_by(
    elementary_or_route_level: pd.DataFrame, group_col: str, weight_col: str
) -> pd.DataFrame:
    """A breakdown by any single column present on the input: carrier type, trunk vs
    non-trunk route class, advance window, or anything else the caller has already
    joined on.

    ``weight_col`` is whatever weight is appropriate for the level being broken down —
    a route-level n_quotes weight, a booking-profile weight, a dgca_pax_share — this
    module does not privilege one grouping over another; it is the same computation
    (:func:`weighted_geometric_rollup`) for every named sub-index CLAUDE.md asks for.
    """
    return weighted_geometric_rollup(elementary_or_route_level, [group_col], weight_col)


__all__ = [
    "COVERAGE_COL",
    "N_QUOTES_COL",
    "VALUE_COL",
    "national_index",
    "route_index",
    "sub_index_by",
    "weighted_geometric_rollup",
]
