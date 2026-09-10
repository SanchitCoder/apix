"""Stage 4 — missing-value and sold-out handling.

Three distinct reasons a cell in the expected sampling grid has no clean observation,
each treated differently (CLAUDE.md principle 2: nothing fails silently):

* **not collected** — the source was blocked, or its collection run otherwise did not
  complete. A coverage gap. No imputation is attempted; it reduces ``coverage_pct``.
* **collected, no availability** — the collector ran successfully but the fare was
  genuinely unavailable (sold out). Imputed by the cell mean within
  ``(route_id, advance_days, carrier_type)``, and the imputed row is flagged
  ``is_imputed = True`` with its ``imputation_method`` recorded. If even that group has
  too little evidence to support a mean, the cell is left unresolved rather than guessed.
* **collected, malformed** — a row exists in ``fare_quote`` but fails a basic sanity
  check (non-positive total, missing identity dimensions). Quarantined for inspection,
  never silently dropped or silently repaired.

See ``docs/imputation.md`` for the narrative version of these rules. Every function here
is pure: DataFrames in, DataFrames out, no database access, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

MissingReason = Literal["not_collected", "sold_out"]

# Run outcomes that count as "the collector actually looked and found nothing there".
# Everything else (BLOCKED, FAILED, PENDING, RUNNING, or no run record at all) means we
# have no evidence the cell was ever genuinely probed.
_RAN_SUCCESSFULLY = frozenset({"SUCCEEDED", "PARTIAL"})

CELL_IDENTITY = (
    "source_id",
    "route_id",
    "carrier_iata",
    "flight_number",
    "advance_days",
    "query_date",
    "travel_date",
)

DEFAULT_IMPUTATION_GROUP = ("route_id", "advance_days", "carrier_type")


def classify_missing_cells(
    expected_cells: pd.DataFrame,
    observed: pd.DataFrame,
    collection_runs: pd.DataFrame,
) -> pd.DataFrame:
    """Which cells of ``expected_cells`` have no row in ``observed``, and why.

    ``expected_cells`` is the sampling grid the collector was supposed to fill —
    one row per ``(source_id, route_id, carrier_iata, flight_number, advance_days,
    query_date, travel_date)`` it should have probed. ``collection_runs`` carries the
    outcome of each attempt: ``source_id``, ``route_id``, ``query_date``, ``status``
    (a ``RunStatus`` value as a string).

    Returns one row per missing cell, with ``missing_reason`` set.
    """
    missing_id = [c for c in CELL_IDENTITY if c not in expected_cells.columns]
    if missing_id:
        raise ValueError(f"classify_missing_cells: expected_cells missing columns: {missing_id}")
    missing_obs = [c for c in CELL_IDENTITY if c not in observed.columns]
    if missing_obs:
        raise ValueError(f"classify_missing_cells: observed missing columns: {missing_obs}")
    run_cols = {"source_id", "route_id", "query_date", "status"}
    if not run_cols.issubset(collection_runs.columns):
        raise ValueError(f"classify_missing_cells: collection_runs missing columns: {run_cols}")

    identity = list(CELL_IDENTITY)
    observed_keys = observed[identity].drop_duplicates()
    merged = expected_cells.merge(observed_keys, on=identity, how="left", indicator=True)
    missing = merged.loc[merged["_merge"] == "left_only", identity].copy()
    if missing.empty:
        missing["missing_reason"] = pd.Series(dtype="object")
        return missing.reset_index(drop=True)

    runs = collection_runs[["source_id", "route_id", "query_date", "status"]].drop_duplicates(
        subset=["source_id", "route_id", "query_date"], keep="last"
    )
    missing = missing.merge(runs, on=["source_id", "route_id", "query_date"], how="left")
    ran_successfully = missing["status"].isin(_RAN_SUCCESSFULLY)
    missing["missing_reason"] = np.where(ran_successfully, "sold_out", "not_collected")
    return missing.drop(columns=["status"]).reset_index(drop=True)


@dataclass(frozen=True)
class ImputationResult:
    """Output of :func:`impute_sold_out`."""

    imputed: pd.DataFrame
    unresolved: pd.DataFrame


def impute_sold_out(
    sold_out_cells: pd.DataFrame,
    clean_quotes: pd.DataFrame,
    imputation_method: str = "cell_mean",
    group_columns: Sequence[str] = DEFAULT_IMPUTATION_GROUP,
    min_group_size: int = 3,
    price_column: str = "total_fare",
) -> ImputationResult:
    """Impute a ``total_fare`` for genuine sell-outs by the group mean.

    ``sold_out_cells`` must carry ``carrier_type`` (join it from the carrier reference
    before calling this). ``clean_quotes`` should already exclude flagged outliers — an
    anomalous price must never pull the mean it would otherwise be screened out of.

    A cell whose group has fewer than ``min_group_size`` clean observations cannot
    support a mean; it is returned in ``unresolved`` instead of being guessed.
    """
    group_cols = list(group_columns)
    missing_sold_out = [c for c in group_cols if c not in sold_out_cells.columns]
    if missing_sold_out:
        raise ValueError(f"impute_sold_out: sold_out_cells missing columns: {missing_sold_out}")
    missing_clean = [c for c in (*group_cols, price_column) if c not in clean_quotes.columns]
    if missing_clean:
        raise ValueError(f"impute_sold_out: clean_quotes missing columns: {missing_clean}")

    if sold_out_cells.empty:
        empty = sold_out_cells.copy()
        empty["total_fare"] = pd.Series(dtype="float64")
        empty["is_imputed"] = pd.Series(dtype="bool")
        empty["imputation_method"] = pd.Series(dtype="object")
        return ImputationResult(imputed=empty, unresolved=sold_out_cells.copy())

    stats = clean_quotes.groupby(group_cols, sort=False)[price_column].agg(["mean", "count"])
    stats = stats.rename(columns={"mean": "_cell_mean", "count": "_cell_n"})

    working = sold_out_cells.merge(stats, on=group_cols, how="left")
    can_impute = working["_cell_n"].fillna(0).ge(min_group_size)

    imputed = working.loc[can_impute].copy()
    imputed[price_column] = imputed["_cell_mean"]
    imputed["is_imputed"] = True
    imputed["imputation_method"] = imputation_method
    imputed = imputed.drop(columns=["_cell_mean", "_cell_n"])

    unresolved = working.loc[~can_impute].drop(columns=["_cell_mean", "_cell_n"]).copy()
    return ImputationResult(
        imputed=imputed.reset_index(drop=True), unresolved=unresolved.reset_index(drop=True)
    )


def with_carrier_type(cells: pd.DataFrame, carrier_type_by_iata: Mapping[str, str]) -> pd.DataFrame:
    """Attach ``carrier_type`` to a cells DataFrame from a ``carrier_iata`` reference."""
    if "carrier_iata" not in cells.columns:
        raise ValueError("with_carrier_type: cells is missing carrier_iata")
    result = cells.copy()
    result["carrier_type"] = result["carrier_iata"].map(carrier_type_by_iata)
    return result


def quarantine_malformed(
    quotes: pd.DataFrame,
    required_columns: Sequence[str] = ("route_id", "carrier_iata", "travel_date", "advance_days"),
    price_column: str = "total_fare",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split ``quotes`` into (kept, quarantined). Quarantined rows carry the reason.

    A row is malformed if a required identity dimension is null, or ``total_fare`` is
    null, non-positive, or non-finite. Quarantined rows are never repaired or dropped
    silently — they are returned for inspection, with ``quarantine_reason`` set.
    """
    missing = [c for c in (*required_columns, price_column) if c not in quotes.columns]
    if missing:
        raise ValueError(f"quarantine_malformed: missing required columns: {missing}")

    if quotes.empty:
        kept = quotes.copy()
        quarantined = quotes.copy()
        quarantined["quarantine_reason"] = pd.Series(dtype="object")
        return kept, quarantined

    price = pd.to_numeric(quotes[price_column], errors="coerce")
    price_bad = price.isna() | (price <= 0) | ~np.isfinite(price)

    dims_bad = pd.Series(False, index=quotes.index)
    for col in required_columns:
        dims_bad = dims_bad | quotes[col].isna()

    reason = pd.Series(pd.NA, index=quotes.index, dtype="object")
    reason.loc[dims_bad] = "missing_identity_dimension"
    reason.loc[price_bad & ~dims_bad] = "invalid_total_fare"

    is_malformed = dims_bad | price_bad
    kept = quotes.loc[~is_malformed].copy()
    quarantined = quotes.loc[is_malformed].copy()
    quarantined["quarantine_reason"] = reason.loc[is_malformed]
    return kept, quarantined


def compute_coverage(
    expected_cells: pd.DataFrame,
    observed: pd.DataFrame,
    missing: pd.DataFrame,
    imputed_cell_keys: pd.DataFrame | None = None,
    group_columns: Sequence[str] = ("route_id", "advance_days"),
) -> pd.DataFrame:
    """Coverage per ``group_columns`` (default ``(route_id, advance_days)``).

    ``coverage_pct`` counts only genuine observations (rows actually present in
    ``observed``) against the expected grid — an imputed sell-out is real analytical
    data for the cleaning output, but it is not evidence that was collected, so it does
    not count toward coverage. ``imputed_cell_keys`` is reported alongside for context.
    """
    group_cols = list(group_columns)
    expected_count = expected_cells.groupby(group_cols, sort=False).size().rename("expected_count")

    observed_cells = observed[list(CELL_IDENTITY)].drop_duplicates()
    observed_count = observed_cells.groupby(group_cols, sort=False).size().rename("observed_count")

    reason_counts = (
        missing.groupby([*group_cols, "missing_reason"], sort=False)
        .size()
        .unstack("missing_reason", fill_value=0)
        if not missing.empty
        else pd.DataFrame(columns=["not_collected", "sold_out"])
    )
    for col in ("not_collected", "sold_out"):
        if col not in reason_counts.columns:
            reason_counts[col] = 0

    coverage = (
        pd.DataFrame(expected_count)
        .join(observed_count, how="left")
        .join(reason_counts[["not_collected", "sold_out"]], how="left")
        .fillna(0)
    )
    coverage["observed_count"] = coverage["observed_count"].astype(int)
    coverage["not_collected_count"] = coverage["not_collected"].astype(int)
    coverage["sold_out_count"] = coverage["sold_out"].astype(int)
    coverage = coverage.drop(columns=["not_collected", "sold_out"])

    if imputed_cell_keys is not None and not imputed_cell_keys.empty:
        imputed_count = (
            imputed_cell_keys.groupby(group_cols, sort=False).size().rename("imputed_count")
        )
        coverage = coverage.join(imputed_count, how="left").fillna({"imputed_count": 0})
        coverage["imputed_count"] = coverage["imputed_count"].astype(int)
    else:
        coverage["imputed_count"] = 0

    coverage["coverage_pct"] = np.where(
        coverage["expected_count"] > 0,
        100.0 * coverage["observed_count"] / coverage["expected_count"],
        0.0,
    )
    return coverage.reset_index()


__all__ = [
    "CELL_IDENTITY",
    "DEFAULT_IMPUTATION_GROUP",
    "ImputationResult",
    "MissingReason",
    "classify_missing_cells",
    "compute_coverage",
    "impute_sold_out",
    "quarantine_malformed",
    "with_carrier_type",
]
