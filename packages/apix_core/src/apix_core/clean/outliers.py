"""Stage 3 — outlier detection.

Two independent screens, computed on ``log(total_fare)`` within each
``(route_id, advance_days, travel_date)`` cell — the natural comparison group, since
price level varies by route and by how close to departure the fare was quoted:

* ``mad_log`` — the Iglewicz & Hoaglin modified z-score on the median absolute
  deviation. Robust to the outliers it is trying to detect, unlike a mean/stdev
  z-score.
* ``iqr`` — the classic Tukey inter-quartile fence.

Both are always computed; which one actually gates (``is_outlier``/``outlier_rule``) is
the configured ``active_rule``. Nothing is dropped here — a flagged row is marked, never
removed, so the index layer can decide how to treat it and an auditor can always see
what was screened out and why.

Pure function: no database access, no I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from apix_core.config.cleaning import OutlierRuleName

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_GROUP_COLUMNS = ("route_id", "advance_days", "travel_date")

# Iglewicz & Hoaglin's constant relating the median absolute deviation to a normal
# standard deviation, so the modified z-score is on a comparable scale to threshold 3.5.
_MAD_CONSISTENCY_CONSTANT = 0.6745


def detect_outliers(
    quotes: pd.DataFrame,
    active_rule: OutlierRuleName,
    mad_threshold: float,
    iqr_k: float,
    min_cell_size: int,
    group_columns: Sequence[str] = DEFAULT_GROUP_COLUMNS,
    price_column: str = "total_fare",
) -> pd.DataFrame:
    """Return ``quotes`` with outlier flags added.

    Adds ``is_outlier_mad`` and ``is_outlier_iqr`` (each rule's independent verdict),
    plus ``is_outlier``/``outlier_rule`` reflecting whichever rule is ``active_rule``.
    A cell with fewer than ``min_cell_size`` quotes is never screened by either rule —
    there is not enough spread in a handful of points to tell a genuine outlier from
    ordinary variation.
    """
    group_cols = list(group_columns)
    missing = [c for c in (*group_cols, price_column) if c not in quotes.columns]
    if missing:
        raise ValueError(f"detect_outliers: missing required columns: {missing}")
    if min_cell_size < 2:
        raise ValueError("min_cell_size must be >= 2")

    result = quotes.copy()
    if result.empty:
        for col in ("is_outlier_mad", "is_outlier_iqr", "is_outlier"):
            result[col] = pd.Series(dtype="bool")
        result["outlier_rule"] = pd.Series(dtype="object")
        return result

    log_price = np.log(result[price_column].astype(float))
    working = result[group_cols].copy()
    working["_log_price"] = log_price
    grouped = working.groupby(group_cols, sort=False)

    group_size = grouped["_log_price"].transform("size")
    eligible = group_size >= min_cell_size

    result["is_outlier_mad"] = eligible & _mad_log_flags(working, group_cols, mad_threshold)
    result["is_outlier_iqr"] = eligible & _iqr_flags(working, group_cols, iqr_k)

    if active_rule is OutlierRuleName.MAD_LOG:
        active_flags = result["is_outlier_mad"]
    else:
        active_flags = result["is_outlier_iqr"]
    result["is_outlier"] = active_flags
    rule_col = pd.Series(active_rule.value, index=result.index)
    result["outlier_rule"] = rule_col.where(active_flags, None)
    return result


def _mad_log_flags(working: pd.DataFrame, group_cols: list[str], threshold: float) -> pd.Series:
    grouped = working.groupby(group_cols, sort=False)
    median = grouped["_log_price"].transform("median")
    abs_dev = (working["_log_price"] - median).abs()
    mad = abs_dev.groupby([working[c] for c in group_cols], sort=False).transform("median")
    mad_safe = mad.where(mad > 0)  # zero MAD (a flat cell) cannot flag anything
    modified_z = _MAD_CONSISTENCY_CONSTANT * (working["_log_price"] - median) / mad_safe
    flags: pd.Series = modified_z.abs().gt(threshold).fillna(False)
    return flags


def _iqr_flags(working: pd.DataFrame, group_cols: list[str], k: float) -> pd.Series:
    grouped = working.groupby(group_cols, sort=False)
    q1 = grouped["_log_price"].transform("quantile", 0.25)
    q3 = grouped["_log_price"].transform("quantile", 0.75)
    iqr = q3 - q1
    lower = q1 - k * iqr
    upper = q3 + k * iqr
    flags: pd.Series = (working["_log_price"] < lower) | (working["_log_price"] > upper)
    return flags


__all__ = ["DEFAULT_GROUP_COLUMNS", "detect_outliers"]
