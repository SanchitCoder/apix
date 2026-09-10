"""Index mathematics — elementary aggregates, multilateral methods, splicing, hedonics
and the aggregation hierarchy.

Everything in this package is a pure function over dataframes, series or arrays: no
database access, no I/O, no logging side-effects, no wall-clock or RNG reads. That is
what makes it testable against hand-computed fixtures and what makes an index run
reproducible (CLAUDE.md principle 4) — see :mod:`apix_core.index.run`.

    apix_core.index.elementary     jevons / dutot / carli
    apix_core.index.multilateral   GEKS-Törnqvist, Time Product Dummy
    apix_core.index.splice         movement / window / half / mean / FBEW / FBMW
    apix_core.index.hedonic        time-dummy quality adjustment
    apix_core.index.weighting      booking-profile (lead-time) window weighting
    apix_core.index.aggregate      route index, national index, sub-indices
    apix_core.index.run            reproducible index_value / revision_log rows
"""

from __future__ import annotations

from apix_core.index.aggregate import (
    COVERAGE_COL,
    N_QUOTES_COL,
    VALUE_COL,
    national_index,
    route_index,
    sub_index_by,
    weighted_geometric_rollup,
)
from apix_core.index.elementary import DEFAULT_FORMULA, carli, dutot, elementary_index, jevons
from apix_core.index.hedonic import HedonicQualityFloorError, HedonicResult, hedonic_time_dummy
from apix_core.index.multilateral import geks_tornqvist, time_product_dummy, tornqvist_bilateral
from apix_core.index.run import IndexRunOutput, run_hash, run_index
from apix_core.index.splice import (
    DEFAULT_METHOD,
    fbew_splice,
    fbmw_splice,
    half_splice,
    mean_splice,
    movement_splice,
    should_rebase,
    splice,
    splice_link_estimate,
    window_splice,
)
from apix_core.index.weighting import combine_advance_windows

__all__ = [
    "COVERAGE_COL",
    "DEFAULT_FORMULA",
    "DEFAULT_METHOD",
    "N_QUOTES_COL",
    "VALUE_COL",
    "HedonicQualityFloorError",
    "HedonicResult",
    "IndexRunOutput",
    "carli",
    "combine_advance_windows",
    "dutot",
    "elementary_index",
    "fbew_splice",
    "fbmw_splice",
    "geks_tornqvist",
    "half_splice",
    "hedonic_time_dummy",
    "jevons",
    "mean_splice",
    "movement_splice",
    "national_index",
    "route_index",
    "run_hash",
    "run_index",
    "should_rebase",
    "splice",
    "splice_link_estimate",
    "sub_index_by",
    "time_product_dummy",
    "tornqvist_bilateral",
    "weighted_geometric_rollup",
    "window_splice",
]
