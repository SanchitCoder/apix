"""Booking-profile weighting: combining the advance-purchase windows into one route
index.

A route's published index is not the average fare across advance-purchase windows —
travellers do not book uniformly across them, so an unweighted average would move with
whatever mix of windows happened to have data this period rather than with price. The
combination needs a *lead-time distribution*: the share of bookings that fall in each
advance-purchase window.

That distribution is read from ``config/method.yaml``'s ``booking_profile`` section
(:class:`apix_core.config.method.BookingProfile`). As of this module's introduction it
is a **stated assumption, not a measurement** — no real Indian-market booking-profile
data has been sourced yet. The config file says so explicitly (its ``source`` field),
and this module does not soften that: :func:`combine_advance_windows` uses whatever
distribution it is given without knowing or caring whether it is real or assumed. Real
data replaces the config value; this function does not change either way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pandas as pd


def combine_advance_windows(
    index_by_window: pd.Series, weights: Mapping[str, float]
) -> tuple[float, float]:
    r"""Weighted-geometric-mean combination of per-window elementary indexes.

    :math:`I_{\text{route}} = \exp\left(\sum_w \tilde{w} \cdot \ln I_w\right)`, where
    :math:`\tilde{w}` is ``weights`` renormalised over whichever windows are actually
    present in ``index_by_window`` — a route missing data in one window still gets a
    combined index, using only the weight mass that survives.

    A geometric (not arithmetic) mean keeps this consistent with every other
    aggregation step in this package (:mod:`apix_core.index.elementary`,
    :mod:`apix_core.index.multilateral`, :mod:`apix_core.index.aggregate`), all of
    which combine log price relatives.

    Returns ``(combined_index, coverage_pct)``, where ``coverage_pct`` is the share of
    the *configured* booking-profile weight mass that windows actually present in the
    data account for — 100.0 only when every configured window has data.
    """
    if index_by_window.empty:
        raise ValueError("index_by_window must have at least one entry")
    if (index_by_window <= 0).any():
        raise ValueError("index values must be strictly positive")
    if not weights:
        raise ValueError("weights must not be empty")
    if any(w < 0 for w in weights.values()):
        raise ValueError("weights must be non-negative")
    total_configured_weight = sum(weights.values())
    if total_configured_weight <= 0:
        raise ValueError("weights must sum to a positive total")

    matched = [w for w in index_by_window.index if w in weights]
    if not matched:
        raise ValueError(
            "no advance-purchase window in index_by_window matches the configured booking profile"
        )
    matched_weight = np.array([weights[w] for w in matched], dtype=np.float64)
    matched_values = index_by_window.loc[matched].to_numpy(dtype=np.float64)

    coverage_pct = float(matched_weight.sum() / total_configured_weight * 100.0)
    normalised = matched_weight / matched_weight.sum()
    combined = float(np.exp(np.sum(normalised * np.log(matched_values))))
    return combined, coverage_pct


__all__ = ["combine_advance_windows"]
