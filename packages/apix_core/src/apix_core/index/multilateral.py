"""Multilateral index methods over a rolling window.

A bilateral chained index (compare period t to t-1, multiply the links together) drifts
when the matched product set changes composition from one link to the next — see
``docs/adr/0002-why-multilateral-index.md``. Airfares churn constantly (flights are
retimed, fare brands renamed, itineraries added and dropped), so APIx never chains.
Instead every period in a rolling window is compared against every other period, and
the comparisons are reconciled into one transitive set of index levels. Transitivity —
the comparison between two periods is the same whether taken directly or through any
third period — is exactly the property chaining lacks, and it is what eliminates chain
drift. ``tests/apix_core/index/test_multilateral.py::test_chain_drift_*`` is the proof.

Both methods here take a *panel*: one row per (period, product) observation, where a
"product" is whatever the caller has decided is the unit of comparison (typically a
(route, advance-purchase window, carrier, ...) cell, or, one level down, the fare bucket
within a cell). A product need not appear in every period — that is the entire point of
a multilateral method — but the panel must have at least two periods and every period
must share at least one product with at least one other period, or there is nothing to
compare.

Required panel columns: ``period`` (any orderable, hashable value — an int period index
or a date), ``product_id`` (hashable), ``price`` (strictly positive), ``share``
(non-negative; the product's expenditure/quantity share within its period, renormalised
here over whichever subset of products two periods actually have in common).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from numpy.typing import NDArray

_REQUIRED_PANEL_COLUMNS = ("period", "product_id", "price", "share")


def _validate_panel(panel: pd.DataFrame, window_days: int) -> None:
    if window_days < 1:
        raise ValueError("window_days must be >= 1")
    missing = [c for c in _REQUIRED_PANEL_COLUMNS if c not in panel.columns]
    if missing:
        raise ValueError(f"panel is missing required columns: {missing}")
    if panel.empty:
        raise ValueError("panel must have at least one observation")
    if (panel["price"] <= 0).any():
        raise ValueError("panel prices must be strictly positive")
    if (panel["share"] < 0).any():
        raise ValueError("panel shares must be non-negative")
    n_periods = panel["period"].nunique()
    if n_periods < 2:
        raise ValueError("a multilateral index requires at least two periods in the window")
    span = panel["period"].max() - panel["period"].min()
    span_days = span.days if hasattr(span, "days") else float(span)
    if span_days > window_days:
        raise ValueError(
            f"panel spans {span_days} days, more than the declared window_days={window_days}"
        )


def _bilateral_log_index(
    p0: NDArray[np.float64],
    p1: NDArray[np.float64],
    s0: NDArray[np.float64],
    s1: NDArray[np.float64],
) -> float:
    """The log bilateral Törnqvist index over already-matched, aligned arrays.

    Shared numeric core of :func:`tornqvist_bilateral` and :func:`geks_tornqvist`, so
    the two never compute the formula two different ways: matching/alignment (pandas
    index work, cheap once) is the only thing that differs between them.
    """
    if p0.size == 0:
        raise ValueError("no products are common to both periods")
    if np.any(p0 <= 0) or np.any(p1 <= 0):
        raise ValueError("prices must be strictly positive")
    avg_share = (s0 + s1) / 2.0
    total = avg_share.sum()
    if total <= 0:
        raise ValueError("matched shares sum to zero; cannot form a weighted comparison")
    weights = avg_share / total
    return float(np.sum(weights * np.log(p1 / p0)))


def tornqvist_bilateral(
    price_0: pd.Series, price_1: pd.Series, share_0: pd.Series, share_1: pd.Series
) -> float:
    r"""Bilateral Törnqvist price index between two periods.

    :math:`P_T(0,1) = \prod_i \left(\frac{p_{i1}}{p_{i0}}\right)^{(s_{i0}+s_{i1})/2}`

    All four arguments are indexed by ``product_id``. Only products present in *all
    four* series are used — the bilateral building block's whole job is to tolerate a
    product that is missing from one side, by simply excluding it from this one
    comparison rather than treating its absence as a price change. Shares are
    renormalised to sum to 1 over that matched subset, so a comparison built from a
    small overlap is still a proper weighted geometric mean.

    Exact time reversal holds by construction:
    ``tornqvist_bilateral(p1, p0, s1, s0) == 1 / tornqvist_bilateral(p0, p1, s0, s1)``.
    """
    common = price_0.index.intersection(price_1.index)
    common = common.intersection(share_0.index).intersection(share_1.index)
    p0 = price_0.loc[common].to_numpy(dtype=np.float64)
    p1 = price_1.loc[common].to_numpy(dtype=np.float64)
    s0 = share_0.loc[common].to_numpy(dtype=np.float64)
    s1 = share_1.loc[common].to_numpy(dtype=np.float64)
    return float(np.exp(_bilateral_log_index(p0, p1, s0, s1)))


def _dense_price_share_matrices(
    panel: pd.DataFrame,
) -> tuple[list[object], NDArray[np.float64], NDArray[np.float64], NDArray[np.bool_]]:
    """``panel`` as (periods x products) dense matrices, for a vectorised GEKS.

    GEKS compares every period against every other: with :math:`M` periods that is
    :math:`M^2` bilateral comparisons, and doing each one through pandas index
    alignment (as :func:`tornqvist_bilateral` does, for its own single-comparison use)
    carries enough per-call overhead to dominate the runtime once :math:`M` is more
    than a handful of periods. Building the dense matrices once and slicing them with
    plain numpy boolean masks inside the :math:`M^2` loop (see :func:`geks_tornqvist`)
    is the same arithmetic with the pandas cost paid once instead of :math:`M^2` times
    — see ``docs/adr/0002-why-multilateral-index.md``: "it has to be optimisable".
    """
    periods = sorted(panel["period"].unique())
    products = sorted(panel["product_id"].unique())
    period_pos = {t: i for i, t in enumerate(periods)}
    product_pos = {p: i for i, p in enumerate(products)}
    t_idx = panel["period"].map(period_pos).to_numpy(dtype=np.int64)
    p_idx = panel["product_id"].map(product_pos).to_numpy(dtype=np.int64)

    m, n = len(periods), len(products)
    price = np.full((m, n), np.nan, dtype=np.float64)
    share = np.zeros((m, n), dtype=np.float64)
    price[t_idx, p_idx] = panel["price"].to_numpy(dtype=np.float64)
    share[t_idx, p_idx] = panel["share"].to_numpy(dtype=np.float64)
    present = ~np.isnan(price)
    return periods, price, share, present


def geks_tornqvist(panel: pd.DataFrame, window_days: int) -> pd.Series:
    """GEKS index over ``panel``, using Törnqvist bilaterals, normalised to 1.0 at the
    window's earliest period.

    For each ordered pair of periods :math:`(l, t)` in the window, compute the log
    bilateral Törnqvist index :math:`\\ln P_T(l,t)`. The GEKS estimate of period *t*
    relative to period *r* is

    :math:`\\ln P_{GEKS}(r,t) = \\bar{C}(t) - \\bar{C}(r)`, where
    :math:`\\bar{C}(t) = \\frac{1}{M}\\sum_{l} \\ln P_T(l,t)`.

    This reduction (row-mean differences rather than a full pairwise minimisation) is
    exact because Törnqvist satisfies time reversal exactly
    (:math:`\\ln P_T(l,t) = -\\ln P_T(t,l)`); it is the standard construction (Ivancic,
    Diewert & Fox, 2011). One consequence, checked by
    ``test_geks_with_two_periods_equals_the_bilateral_index``: with exactly two periods
    in the window, GEKS collapses to the plain bilateral Törnqvist index between them.

    Returns a ``pd.Series`` indexed by period, in chronological order, with the first
    (earliest) period equal to exactly 1.0.
    """
    _validate_panel(panel, window_days)
    periods, price, share, present = _dense_price_share_matrices(panel)
    m = len(periods)
    log_bilateral = np.zeros((m, m), dtype=np.float64)
    for i in range(m):
        for j in range(m):
            if i == j:
                continue
            mask = present[i] & present[j]
            try:
                log_bilateral[i, j] = _bilateral_log_index(
                    price[i, mask], price[j, mask], share[i, mask], share[j, mask]
                )
            except ValueError as exc:
                raise ValueError(f"{exc} (periods {periods[i]!r} and {periods[j]!r})") from exc
    c = log_bilateral.mean(axis=0)
    levels = np.exp(c - c[0])
    return pd.Series(levels, index=pd.Index(periods, name="period"), name="geks_tornqvist")


def time_product_dummy(panel: pd.DataFrame, window_days: int) -> pd.Series:
    r"""Time Product Dummy multilateral index via weighted least squares.

    Regresses :math:`\ln(\text{price})` on a full set of product dummies and time
    dummies (weighted by each observation's ``share``), with the window's earliest
    period and the lexicographically-first product held out as the reference category:

    :math:`\ln p_{it} = \alpha + \sum_{t \neq 0} \delta_t D_t
    + \sum_{i \neq 0} \gamma_i D_i + \varepsilon_{it}`

    The index for period *t* is :math:`\exp(\delta_t)`, with :math:`\delta_0 := 0` so
    the earliest period is exactly 1.0. TPD tolerates a sparser, more unbalanced panel
    than GEKS-Törnqvist (every observation contributes to one joint regression rather
    than needing pairwise overlap) and needs no separate bilateral step.

    A well-known special case, checked by ``test_tpd_two_periods_equals_unweighted_jevons``:
    with exactly two periods and equal weights, the time-dummy coefficient reduces
    exactly to the log of the unweighted Jevons index across the products common to
    both periods (Diewert, 2004, hedonic time-dummy method — the bilateral case is the
    country-product-dummy method).
    """
    _validate_panel(panel, window_days)
    periods = sorted(panel["period"].unique())
    products = sorted(panel["product_id"].unique())
    n_periods = len(periods)
    n_products = len(products)

    period_pos = {t: i for i, t in enumerate(periods)}
    product_pos = {p: i for i, p in enumerate(products)}
    t_idx = panel["period"].map(period_pos).to_numpy(dtype=np.int64)
    p_idx = panel["product_id"].map(product_pos).to_numpy(dtype=np.int64)

    n = len(panel)
    time_dummies = np.eye(n_periods, dtype=np.float64)[t_idx][:, 1:]
    product_dummies = np.eye(n_products, dtype=np.float64)[p_idx][:, 1:]
    design = np.hstack([np.ones((n, 1), dtype=np.float64), time_dummies, product_dummies])

    y = np.log(panel["price"].to_numpy(dtype=np.float64))
    weights = panel["share"].to_numpy(dtype=np.float64)
    if np.all(weights == 0):
        # _validate_panel already forbids negative shares, so all-zero (everyone
        # unweighted) is the only degenerate case left to handle: fall back to an
        # unweighted (equal-weight) regression rather than dividing by zero.
        weights = np.ones(n, dtype=np.float64)
    sqrt_w = np.sqrt(weights)
    design_weighted = design * sqrt_w[:, None]
    y_weighted = y * sqrt_w

    rank = np.linalg.matrix_rank(design_weighted)
    if rank < design_weighted.shape[1]:
        raise ValueError(
            "the (period, product) design matrix is rank-deficient — the panel is too "
            "sparse to separate time effects from product effects over this window"
        )

    beta, *_ = np.linalg.lstsq(design_weighted, y_weighted, rcond=None)
    time_coefficients = np.concatenate([[0.0], beta[1:n_periods]])
    levels = np.exp(time_coefficients)
    return pd.Series(levels, index=pd.Index(periods, name="period"), name="time_product_dummy")


__all__ = ["geks_tornqvist", "time_product_dummy", "tornqvist_bilateral"]
