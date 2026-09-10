"""Sell-out velocity: how quickly availability disappears per route.

Built on top of :func:`apix_core.clean.missing.classify_missing_cells`'s existing
``sold_out`` classification, not a new detector — a cell is only evidence of a sell-out
here because the cleaning pipeline already determined the collector ran successfully
and found nothing (as opposed to not having been collected at all; see
docs/imputation.md). ``advance_days`` counts days before departure, so the *largest*
``advance_days`` at which a cell is already sold out is the earliest point (furthest
from departure) demand was observed to have closed it out — a higher value means faster
sell-out, i.e. more early demand pressure.
"""

from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = ("route_id", "carrier_type", "advance_days", "travel_date", "missing_reason")

_OUTPUT_COLUMNS = (
    "route_id",
    "carrier_type",
    "travel_date",
    "earliest_sold_out_advance_days",
    "n_sold_out_observations",
)


def compute_sellout_velocity(missing_cells: pd.DataFrame, min_group_size: int = 1) -> pd.DataFrame:
    """One row per ``(route_id, carrier_type, travel_date)`` with at least
    ``min_group_size`` sold-out observations: the largest ``advance_days`` at which a
    sold-out cell was observed (the velocity signal) and how many observations support
    it. A group with fewer than ``min_group_size`` sold-out observations is dropped —
    the same "not enough evidence to report a number" refusal
    :func:`apix_core.clean.missing.impute_sold_out` uses for its own group-size floor.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in missing_cells.columns]
    if missing:
        raise ValueError(f"compute_sellout_velocity: missing required columns: {missing}")

    sold_out = missing_cells.loc[missing_cells["missing_reason"] == "sold_out"]
    if sold_out.empty:
        return pd.DataFrame(columns=list(_OUTPUT_COLUMNS))

    group_cols = ["route_id", "carrier_type", "travel_date"]
    result = (
        sold_out.groupby(group_cols)["advance_days"]
        .agg(earliest_sold_out_advance_days="max", n_sold_out_observations="count")
        .reset_index()
    )
    result = result.loc[result["n_sold_out_observations"] >= min_group_size]
    return result[list(_OUTPUT_COLUMNS)].reset_index(drop=True)


__all__ = ["REQUIRED_COLUMNS", "compute_sellout_velocity"]
