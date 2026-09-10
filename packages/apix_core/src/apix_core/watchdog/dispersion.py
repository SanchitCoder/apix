"""Personalised-pricing dispersion statistic.

Turns one probe's N near-simultaneous session observations of the identical query into
a per-(source, flight, instant) dispersion statistic. This module only computes the
number — it does not, and cannot, say *why* fares differed across sessions. See
docs/personalisation-probe.md for the full method and the required caveat: dispersion
has innocent explanations (cache staleness, inventory/seat-map movement between
near-simultaneous requests, promo/session pricing) and a nonzero statistic is not proof
of personalisation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

REQUIRED_OBSERVATION_COLUMNS = (
    "source_code",
    "flight_key",
    "probed_at",
    "session_id",
    "total_fare",
)
STATISTIC_NAME = "coefficient_of_variation"


def compute_dispersion(observations: pd.DataFrame) -> pd.DataFrame:
    """One row per ``(source_code, flight_key, probed_at)`` probe instance: the
    coefficient of variation (population std / mean) of ``total_fare`` across the
    session profiles that queried it, plus ``min_fare``/``max_fare``/``n_sessions``
    for context. A probe instance with a single session has a defined dispersion of
    exactly 0.0 — there is nothing to disperse, not a missing value.
    """
    missing = [c for c in REQUIRED_OBSERVATION_COLUMNS if c not in observations.columns]
    if missing:
        raise ValueError(f"compute_dispersion: observations missing required columns: {missing}")
    if observations.empty:
        raise ValueError("compute_dispersion: observations must have at least one row")
    if (observations["total_fare"] <= 0).any():
        raise ValueError("compute_dispersion: total_fare must be strictly positive")

    group_cols = ["source_code", "flight_key", "probed_at"]
    grouped = observations.groupby(group_cols)["total_fare"]
    stats = grouped.agg(
        n_sessions="count", mean_fare="mean", std_fare="std", min_fare="min", max_fare="max"
    ).reset_index()
    stats["std_fare"] = stats["std_fare"].fillna(0.0)
    stats["value"] = np.where(stats["mean_fare"] > 0, stats["std_fare"] / stats["mean_fare"], 0.0)
    stats["statistic_name"] = STATISTIC_NAME
    return stats[
        [
            "source_code",
            "flight_key",
            "probed_at",
            "statistic_name",
            "value",
            "n_sessions",
            "min_fare",
            "max_fare",
        ]
    ]


__all__ = ["REQUIRED_OBSERVATION_COLUMNS", "STATISTIC_NAME", "compute_dispersion"]
