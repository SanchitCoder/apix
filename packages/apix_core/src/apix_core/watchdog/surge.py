"""Surge detection: flag a (route, date) cell beyond a band around its own trailing
seasonal baseline.

Deliberately per-route, not cross-route: a route's own history is the only honest
baseline for whether *its* price is unusual — comparing across routes would conflate
surge with the routes' ordinary price-level differences. Assumes one row per
``(route_code, travel_date)`` — a row-count trailing window is used as an
approximation of a calendar-day window, which is exact when the input has no gaps and
approximate when it does (a genuine collection gap narrows the effective baseline
window rather than silently stretching it, which is the safer direction to be wrong in).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

    from apix_core.config.watchdog import SurgeConfig

REQUIRED_COLUMNS = ("route_code", "travel_date", "fare")


def detect_surges(fares: pd.DataFrame, config: SurgeConfig) -> pd.DataFrame:
    """One row per input cell, with its trailing per-route baseline and whether it is
    a surge: ``abs(fare - baseline_median) > band_width_k * baseline_mad``.

    A cell without at least ``config.min_history_periods`` of trailing history for its
    route gets ``baseline_available = False`` and ``is_surge = False`` — an
    undetermined cell is reported as undetermined, never guessed at (CLAUDE.md
    principle 2). A cell whose trailing baseline has zero spread (``baseline_mad ==
    0``) also cannot be flagged: any band width around a single repeated value would
    flag every deviation, which is not a meaningful surge signal.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in fares.columns]
    if missing:
        raise ValueError(f"detect_surges: fares missing required columns: {missing}")
    if fares.empty:
        raise ValueError("detect_surges: fares must have at least one row")
    if (fares["fare"] <= 0).any():
        raise ValueError("detect_surges: fare must be strictly positive")

    df = fares.sort_values(["route_code", "travel_date"]).reset_index(drop=True)
    baseline_median = np.full(len(df), np.nan)
    baseline_mad = np.full(len(df), np.nan)

    for _, group in df.groupby("route_code", sort=False):
        idx = group.index.to_numpy()
        fare = group["fare"].to_numpy(dtype=np.float64)
        for i in range(len(fare)):
            window_start = max(0, i - config.baseline_window_days)
            history = fare[window_start:i]  # trailing, excludes the current row
            if len(history) >= config.min_history_periods:
                median = float(np.median(history))
                mad = float(np.median(np.abs(history - median)))
                baseline_median[idx[i]] = median
                baseline_mad[idx[i]] = mad

    df["baseline_median"] = baseline_median
    df["baseline_mad"] = baseline_mad
    df["baseline_available"] = df["baseline_median"].notna()
    band = config.band_width_k * df["baseline_mad"]
    df["is_surge"] = (
        df["baseline_available"]
        & (df["baseline_mad"] > 0)
        & ((df["fare"] - df["baseline_median"]).abs() > band)
    )
    return df[
        [
            "route_code",
            "travel_date",
            "fare",
            "baseline_median",
            "baseline_mad",
            "baseline_available",
            "is_surge",
        ]
    ]


__all__ = ["REQUIRED_COLUMNS", "detect_surges"]
