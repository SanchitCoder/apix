"""Elementary aggregate formulas — the lowest level of the index, below the level at
which expenditure weights exist.

An elementary aggregate turns a set of matched price pairs, one per product observed in
both the base period and the current period, into a single price relative. "Matched"
means paired by product identity (here: a specific (route, advance-purchase window,
carrier, ...) cell) — an unmatched price on either side is simply excluded, never
guessed at.

Jevons is the published default (see :data:`DEFAULT_FORMULA` and
``config/method.yaml``). Carli is implemented only for comparison: it is rejected as a
publishable formula by :class:`apix_core.config.method.MethodConfigFile`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from apix_core.config.method import ElementaryFormula

if TYPE_CHECKING:
    from numpy.typing import ArrayLike, NDArray

DEFAULT_FORMULA = ElementaryFormula.JEVONS


def _matched_pair(
    p_t: ArrayLike, p_0: ArrayLike
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Validate and coerce a pair of matched price arrays.

    Both arrays must be the same length (position ``i`` in each is the same product),
    non-empty, and strictly positive — a non-positive fare is not a price, and letting
    one through would make ``log`` silently produce ``nan``/``-inf`` instead of a clear
    failure.
    """
    a = np.asarray(p_t, dtype=np.float64)
    b = np.asarray(p_0, dtype=np.float64)
    if a.shape != b.shape:
        raise ValueError(
            f"p_t and p_0 must be matched, same-shape arrays; got {a.shape} and {b.shape}"
        )
    if a.ndim != 1:
        raise ValueError("p_t and p_0 must be one-dimensional (one entry per product)")
    if a.size == 0:
        raise ValueError("at least one matched price pair is required")
    if np.any(a <= 0) or np.any(b <= 0):
        raise ValueError("prices must be strictly positive")
    return a, b


def jevons(p_t: ArrayLike, p_0: ArrayLike) -> float:
    r"""Geometric mean of price relatives: :math:`\exp(\text{mean}(\ln(p_t / p_0)))`.

    This is the published default elementary formula (``config/method.yaml``,
    :data:`DEFAULT_FORMULA`). Airfares are exactly the case Jevons is built for: a
    stratum of matched itineraries with no observed quantities, priced dynamically and
    volatile day to day and channel to channel. Two properties make it the right
    choice over :func:`carli` and :func:`dutot` here:

    1. **Time reversal.** ``jevons(p_t, p_0) * jevons(p_0, p_t) == 1`` exactly, for any
       set of matched prices — because it is the exponential of an arithmetic mean of
       logs, and negating a sum negates its mean. Carli fails this test: it is the
       arithmetic mean of ratios, and by Jensen's inequality the arithmetic mean of a
       set of numbers and of their reciprocals cannot both invert cleanly unless every
       ratio is identical. Carli is therefore upward-biased whenever prices move
       around a stable level — precisely the day-to-day, channel-to-channel bouncing
       that dynamic airline pricing produces. Publishing Carli here would
       systematically overstate airfare inflation, which is why
       :class:`apix_core.config.method.MethodConfigFile` refuses it outright as a
       published formula.
    2. **Consistency with the rest of this module.** ``log(jevons(...))`` is the
       arithmetic mean of the log price relatives, so it composes cleanly with the
       Törnqvist/GEKS multilateral index (:mod:`apix_core.index.multilateral`), which
       is itself built from log price relatives, and with the log-additive weighted
       roll-ups in :mod:`apix_core.index.aggregate`.

    Jevons is the ILO/Eurostat CPI manual's standard recommendation for an elementary
    stratum where expenditure weights are unavailable, which is exactly this stratum:
    no quantity is ever observed for a displayed fare.
    """
    a, b = _matched_pair(p_t, p_0)
    return float(np.exp(np.mean(np.log(a / b))))


def dutot(p_t: ArrayLike, p_0: ArrayLike) -> float:
    """Ratio of arithmetic means: ``mean(p_t) / mean(p_0)``.

    This is what a naively-computed "average fare, then vs. then" would give. It is
    implemented for diagnostics and comparison only — Dutot is sensitive to the units
    and scale of individual products (a single very expensive itinerary dominates the
    mean) and is not the published formula.
    """
    a, b = _matched_pair(p_t, p_0)
    return float(np.mean(a) / np.mean(b))


def carli(p_t: ArrayLike, p_0: ArrayLike) -> float:
    """Arithmetic mean of price relatives: ``mean(p_t / p_0)``.

    Implemented for comparison only. Carli is upward-biased and fails the
    time-reversal test (see :func:`jevons`); ``MethodConfigFile`` refuses it as a
    published formula.
    """
    a, b = _matched_pair(p_t, p_0)
    return float(np.mean(a / b))


_FORMULAS = {
    ElementaryFormula.JEVONS: jevons,
    ElementaryFormula.DUTOT: dutot,
    ElementaryFormula.CARLI: carli,
}


def elementary_index(p_t: ArrayLike, p_0: ArrayLike, formula: ElementaryFormula) -> float:
    """Dispatch to the configured elementary formula."""
    try:
        fn = _FORMULAS[formula]
    except KeyError as exc:  # pragma: no cover — exhaustive over the enum
        raise ValueError(f"unknown elementary formula: {formula!r}") from exc
    return fn(p_t, p_0)


__all__ = [
    "DEFAULT_FORMULA",
    "carli",
    "dutot",
    "elementary_index",
    "jevons",
]
