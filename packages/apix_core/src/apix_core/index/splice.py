"""Splicing: extending an already-published series with one new period from a rolled
multilateral window, without ever revising a published value.

A multilateral method (:mod:`apix_core.index.multilateral`) estimates a full set of
index levels over its window every time the window rolls forward by one period — which
means it re-estimates levels for periods that were *already published* under the
previous window. Publishing those re-estimates directly would revise history every
month, which CLAUDE.md forbids outright (principle 4) and which a national statistics
office will not accept. Splicing is how the two requirements — re-estimate with the
latest data, but never revise an already-published number — are reconciled: only the
*newest* period in the window is ever appended to the published series, using a growth
factor derived from the window, applied to the immediately preceding *published* value.

Every function here takes the same two inputs:

* ``published``: a ``pd.Series`` indexed by period, of already-fixed, immutable index
  levels. Must cover every period in ``window_index`` except the newest.
* ``window_index``: a ``pd.Series`` indexed by period, in chronological order, being
  the current window's own multilateral estimate (from
  :func:`apix_core.index.multilateral.geks_tornqvist` or
  :func:`~apix_core.index.multilateral.time_product_dummy`). Its own normalisation
  (i.e. what the earliest period in the window equals) is irrelevant — every splice
  formula below uses only *ratios* within ``window_index``, so any consistent
  normalisation cancels out.

Each returns the single new published value for the newest period in ``window_index``.
Nothing here mutates ``published``; the caller decides how to record the new value (see
:mod:`apix_core.index.run`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from apix_core.config.method import SpliceMethod

if TYPE_CHECKING:
    import pandas as pd


def _validate(published: pd.Series, window_index: pd.Series) -> None:
    if len(window_index) < 2:
        raise ValueError("a window needs at least two periods to splice a new one on")
    if (window_index <= 0).any():
        raise ValueError("window index levels must be strictly positive")
    required = window_index.index[:-1]
    missing = [p for p in required if p not in published.index]
    if missing:
        raise ValueError(f"published series is missing required periods: {missing}")
    if (published.loc[required] <= 0).any():
        raise ValueError("published index levels must be strictly positive")


def splice_link_estimate(published: pd.Series, window_index: pd.Series, k: int) -> float:
    """The published estimate for the newest period, linking back ``k`` periods.

    ``k=1`` is the movement splice; ``k = len(window_index) - 1`` (the whole window) is
    the window splice. This is the shared primitive every named splice method below
    reduces to — see each one's docstring for which ``k`` it uses.

    :math:`\\hat{I}^{(k)}_{\\text{new}} = I_{\\text{new} - k} \\times
    \\dfrac{Q_{\\text{new}}}{Q_{\\text{new}-k}}`

    where :math:`I` is the already-published (immutable) series and :math:`Q` is this
    window's own index. Both the published anchor and the window ratio are taken from
    the same calendar period, ``k`` steps before the newest, so the formula is exact
    regardless of how the window itself is normalised.
    """
    _validate(published, window_index)
    n = len(window_index)
    if not (1 <= k <= n - 1):
        raise ValueError(f"k must be between 1 and {n - 1} (the window has {n} periods)")
    link_period = window_index.index[-1 - k]
    anchor = float(published.loc[link_period])
    ratio = float(window_index.iloc[-1] / window_index.iloc[-1 - k])
    return anchor * ratio


def movement_splice(published: pd.Series, window_index: pd.Series) -> float:
    """Link on the most recent period-on-period movement in the new window (``k=1``).

    Extends the published series by the smallest possible piece of new information:
    only the growth between the two newest periods in the window. This is the
    shipped default in ``config/method.yaml`` (see
    ``docs/adr/0002-why-multilateral-index.md``): the published back-series must stay
    stable when the window rolls, and movement splice changes the least about how the
    newest point was derived.
    """
    return splice_link_estimate(published, window_index, 1)


def window_splice(published: pd.Series, window_index: pd.Series) -> float:
    """Link across the whole window (``k = len(window_index) - 1``): the newest period
    against the window's own oldest period.

    Uses more of the window's information than :func:`movement_splice` at the cost of
    being more exposed to whatever happened at the window's start.
    """
    return splice_link_estimate(published, window_index, len(window_index) - 1)


def half_splice(published: pd.Series, window_index: pd.Series) -> float:
    """Link at the midpoint of the window (``k = ceil((len(window_index) - 1) / 2)``).

    A compromise between :func:`movement_splice` and :func:`window_splice`.
    """
    n = len(window_index)
    k = -(-(n - 1) // 2)  # ceil division, no float rounding surprises
    return splice_link_estimate(published, window_index, k)


def mean_splice(published: pd.Series, window_index: pd.Series) -> float:
    """Geometric mean, over every possible link point, of :func:`splice_link_estimate`.

    :math:`\\hat{I}_{\\text{new}} = \\left(\\prod_{k=1}^{L-1}
    \\hat{I}^{(k)}_{\\text{new}}\\right)^{1/(L-1)}`

    Diewert & Fox (2017): rather than committing to one link point (movement, window or
    half), average across all of them. This is the least sensitive to any single link
    period being an outlier, which is why it is the pure-function default here
    (:data:`DEFAULT_METHOD`) — though ``config/method.yaml`` currently ships
    ``movement`` for the stability reason documented on :func:`movement_splice` and in
    the ADR; config, not this default, governs what is actually published.
    """
    _validate(published, window_index)
    n = len(window_index)
    estimates = np.array(
        [splice_link_estimate(published, window_index, k) for k in range(1, n)],
        dtype=np.float64,
    )
    return float(np.exp(np.mean(np.log(estimates))))


def fbew_splice(published: pd.Series, window_index: pd.Series) -> float:
    """Fixed Base Expanding Window: window splice over an expanding, not rolling,
    window.

    FBEW does not change the *linking formula* — it changes how the window passed in
    as ``window_index`` is built: each new period, the caller extends the same window
    by one more period (fixed base, growing length) rather than dropping the oldest
    observation as a rolling window would. Given such a window, extending the
    published series is exactly :func:`window_splice`: link the newest period back to
    the window's own (fixed) base. This function exists as its own name — rather than
    telling callers to use ``window_splice`` and remember the equivalence — so that
    ``config/method.yaml``'s ``splice_method: fbew`` reads as what it means, and so the
    scheduled rebase point (see :func:`should_rebase`) has an obvious call site.
    """
    return window_splice(published, window_index)


def fbmw_splice(published: pd.Series, window_index: pd.Series) -> float:
    """Fixed Base Moving Window: like :func:`fbew_splice`, but the window has a fixed
    length that rolls forward, and the anchor period is refreshed only at scheduled
    rebase points (:func:`should_rebase`) — annually, typically — rather than every
    period. Between rebases this is identical to :func:`window_splice`, linking the
    newest period back to the window's current (fixed-until-rebase) base; scheduling
    the rebase itself is the caller's responsibility.
    """
    return window_splice(published, window_index)


def should_rebase(periods_since_last_rebase: int, rebase_every: int) -> bool:
    """Whether the current period is a scheduled FBEW/FBMW rebase point.

    ``periods_since_last_rebase`` is 0 on the period a base was last (re)established;
    a rebase is due once that count reaches ``rebase_every`` (e.g. 12, for an annual
    rebase on monthly data).
    """
    if rebase_every < 1:
        raise ValueError("rebase_every must be >= 1")
    if periods_since_last_rebase < 0:
        raise ValueError("periods_since_last_rebase must be >= 0")
    return periods_since_last_rebase >= rebase_every


DEFAULT_METHOD = SpliceMethod.MEAN

_SPLICERS = {
    SpliceMethod.MOVEMENT: movement_splice,
    SpliceMethod.WINDOW: window_splice,
    SpliceMethod.HALF: half_splice,
    SpliceMethod.MEAN: mean_splice,
    SpliceMethod.FBEW: fbew_splice,
    SpliceMethod.FBMW: fbmw_splice,
}


def splice(method: SpliceMethod, published: pd.Series, window_index: pd.Series) -> float:
    """Dispatch to the configured splice method."""
    try:
        fn = _SPLICERS[method]
    except KeyError as exc:  # pragma: no cover — exhaustive over the enum
        raise ValueError(f"unknown splice method: {method!r}") from exc
    return fn(published, window_index)


__all__ = [
    "DEFAULT_METHOD",
    "fbew_splice",
    "fbmw_splice",
    "half_splice",
    "mean_splice",
    "movement_splice",
    "should_rebase",
    "splice",
    "splice_link_estimate",
    "window_splice",
]
