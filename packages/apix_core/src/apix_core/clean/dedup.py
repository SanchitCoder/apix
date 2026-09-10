"""Stage 1 — deduplication.

The same physical flight is quoted by several sources (an airline's own site, one or
more OTAs). Every quote is kept — none is dropped here — but rows describing the same
flight are tagged with a shared ``flight_key`` so a downstream consumer (the elementary
aggregate builder in ``apix_core.index``) can choose one observation per flight per
source-class without double-counting the same seat as several independent price points.

Pure function: takes and returns a DataFrame, no I/O, no database access.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Iterable

# Every flight_key is a uuid5 under this namespace, derived from the matched flight's
# identity — deterministic given the same inputs and tolerance, per CLAUDE.md
# reproducibility principle.
FLIGHT_KEY_NAMESPACE = uuid.UUID("2b6c9a3d-6e0a-4a9e-8a0e-7e6c8f0a3b5e")

REQUIRED_COLUMNS = (
    "id",
    "carrier_iata",
    "flight_number",
    "travel_date",
    "dep_datetime_local",
)


def assign_flight_key(quotes: pd.DataFrame, dep_time_tolerance_minutes: int) -> pd.DataFrame:
    """Return ``quotes`` with a ``flight_key`` column added.

    Quotes are grouped by ``(carrier_iata, flight_number, travel_date)`` and, within
    each group, clustered by ``dep_datetime_local``: sorted by departure time, a new
    cluster starts whenever the gap from the *start* of the current cluster exceeds
    ``dep_time_tolerance_minutes``. This is a single deterministic pass (not a
    transitive closure over pairwise distances), which keeps it stable and cheap over
    a full collection window; it is documented, not hidden, because it means two
    quotes at the edges of a long-lived flat cluster can be more than the tolerance
    apart from each other even though each is within tolerance of the cluster start.

    No row is dropped or reordered relative to its original index.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in quotes.columns]
    if missing:
        raise ValueError(f"assign_flight_key: missing required columns: {missing}")
    if dep_time_tolerance_minutes < 0:
        raise ValueError("dep_time_tolerance_minutes must be >= 0")

    if quotes.empty:
        return quotes.assign(flight_key=pd.Series(dtype="object"))

    tolerance = pd.Timedelta(minutes=dep_time_tolerance_minutes)
    working = quotes.copy()
    working["_dep_dt"] = pd.to_datetime(working["dep_datetime_local"])

    flight_keys = pd.Series(index=working.index, dtype="object")
    group_cols = ["carrier_iata", "flight_number", "travel_date"]
    for group_values, group in working.groupby(group_cols, sort=False, dropna=False):
        ordered = group.sort_values(["_dep_dt", "id"], kind="mergesort")
        cluster_start = ordered["_dep_dt"].iloc[0]
        cluster_index = 0
        for idx, dep_dt in zip(ordered.index, ordered["_dep_dt"], strict=True):
            if dep_dt - cluster_start > tolerance:
                cluster_index += 1
                cluster_start = dep_dt
            flight_keys.loc[idx] = _flight_key(group_values, cluster_index)

    return quotes.assign(flight_key=flight_keys)


def _flight_key(group_values: tuple[object, ...] | object, cluster_index: int) -> str:
    values: Iterable[object] = group_values if isinstance(group_values, tuple) else (group_values,)
    canonical = "|".join(str(v) for v in (*values, cluster_index))
    return str(uuid.uuid5(FLIGHT_KEY_NAMESPACE, canonical))


__all__ = ["FLIGHT_KEY_NAMESPACE", "assign_flight_key"]
