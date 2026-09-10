"""Orchestrates the five cleaning stages into one ``fare_quote_clean``-shaped output.

    raw fare_quote rows
        -> quarantine_malformed          (stage 4a)
        -> assign_flight_key             (stage 1)
        -> decompose_fares               (stage 2)
        -> detect_outliers               (stage 3)
        -> classify_missing_cells        (stage 4b)
        -> impute_sold_out               (stage 4c)
        -> build_quality_vector          (stage 5)

Every stage above is independently testable and importable on its own; this module only
wires them together in the right order and shapes the combined result the way
``fare_quote_clean`` expects it. Still a pure function: every input is a DataFrame (or a
plain mapping) the caller has already pulled out of the database; nothing in here
queries anything.

One gap by design: an imputed row has no real departure time, so its ``dep_hour_bucket``
and ``stops`` are left null even though the ``fare_quote_clean`` column is ``NOT NULL``.
A caller persisting these rows must backfill both from the flight's schedule (keyed by
``carrier_iata``/``flight_number``) before insert — see docs/imputation.md. Never guess
a departure hour here.

``CLEAN_COLUMNS`` carries one column beyond the ``fare_quote_clean`` table itself:
``taxes``, kept alongside ``base_fare`` because :mod:`apix_core.clean.gates` needs it
for the tax-share quality gate. A caller persisting to the database drops it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from apix_core.clean.decompose import decompose_fares
from apix_core.clean.dedup import assign_flight_key
from apix_core.clean.missing import (
    CELL_IDENTITY,
    classify_missing_cells,
    compute_coverage,
    impute_sold_out,
    quarantine_malformed,
    with_carrier_type,
)
from apix_core.clean.outliers import detect_outliers
from apix_core.clean.quality import build_quality_vector

if TYPE_CHECKING:
    from collections.abc import Mapping
    from decimal import Decimal

    from apix_core.config.cleaning import CleaningConfig

CLEAN_COLUMNS = (
    "quote_id",
    "quote_collected_at",
    "snapshot_id",
    "route_id",
    "carrier_iata",
    "travel_date",
    "advance_days",
    "dep_hour_bucket",
    "stops",
    "base_fare",
    "taxes",
    "total_fare",
    "is_outlier",
    "outlier_rule",
    "is_imputed",
    "imputation_method",
    "quality_vector",
)


@dataclass(frozen=True)
class CleanResult:
    """Output of :func:`clean_quotes`."""

    clean: pd.DataFrame
    quarantined: pd.DataFrame
    unresolved: pd.DataFrame
    coverage: pd.DataFrame


def clean_quotes(
    quotes: pd.DataFrame,
    expected_cells: pd.DataFrame,
    collection_runs: pd.DataFrame,
    carrier_type_by_iata: Mapping[str, str],
    airport_udf: Mapping[str, Decimal],
    snapshot_id: str,
    config: CleaningConfig,
) -> CleanResult:
    """Run all five stages over ``quotes`` and return a ``fare_quote_clean``-shaped result.

    ``quotes`` is raw ``fare_quote`` rows (one collection window's worth), each carrying
    at minimum: ``id``, ``source_id``, ``collected_at``, ``route_id``, ``carrier_iata``,
    ``flight_number``, ``origin_iata``, ``dep_datetime_local``, ``travel_date``,
    ``advance_days``, ``stops``, ``refundable``, ``baggage_included``, ``base_fare``,
    ``taxes``, ``udf``, ``convenience_fee``, ``total_fare``. ``expected_cells`` and
    ``collection_runs`` are as documented in :mod:`apix_core.clean.missing`.
    """
    kept, quarantined = quarantine_malformed(quotes)

    kept = assign_flight_key(kept, config.dedup.dep_time_tolerance_minutes)
    kept = decompose_fares(kept, airport_udf, config.decomposition.tax_rate)
    kept = detect_outliers(
        kept,
        config.outliers.active_rule,
        config.outliers.mad_threshold,
        config.outliers.iqr_k,
        config.outliers.min_cell_size,
    )
    kept["carrier_type"] = kept["carrier_iata"].map(carrier_type_by_iata)
    kept["dep_hour_bucket"] = pd.to_datetime(kept["dep_datetime_local"]).dt.hour

    observed_for_missing = kept.rename(
        columns={"id": "quote_id", "collected_at": "quote_collected_at"}
    )
    observed_for_missing["source_id"] = kept["source_id"]
    query_date = pd.to_datetime(kept["travel_date"]) - pd.to_timedelta(
        kept["advance_days"], unit="D"
    )
    observed_for_missing["query_date"] = query_date.dt.date
    missing = classify_missing_cells(
        expected_cells, observed_for_missing[list(CELL_IDENTITY)], collection_runs
    )
    sold_out = with_carrier_type(
        missing.loc[missing["missing_reason"] == "sold_out"], carrier_type_by_iata
    )
    non_outlier = with_carrier_type(kept.loc[~kept["is_outlier"]], carrier_type_by_iata)
    imputation = impute_sold_out(
        sold_out,
        non_outlier,
        group_columns=config.imputation.sellout_group_columns,
        min_group_size=config.imputation.min_group_size,
    )

    observed_clean = _observed_to_clean_shape(kept, snapshot_id)
    imputed_clean = _imputed_to_clean_shape(imputation.imputed, snapshot_id)
    clean = pd.concat([observed_clean, imputed_clean], ignore_index=True)[list(CLEAN_COLUMNS)]
    # An empty imputed_clean has no dtype information; concat can otherwise degrade
    # these to plain-object columns, which silently breaks boolean indexing on them.
    clean["is_outlier"] = clean["is_outlier"].astype(bool)
    clean["is_imputed"] = clean["is_imputed"].astype(bool)

    coverage = compute_coverage(expected_cells, observed_for_missing, missing, imputation.imputed)

    return CleanResult(
        clean=clean, quarantined=quarantined, unresolved=imputation.unresolved, coverage=coverage
    )


def _observed_to_clean_shape(kept: pd.DataFrame, snapshot_id: str) -> pd.DataFrame:
    result = pd.DataFrame(
        {
            "quote_id": kept["id"],
            "quote_collected_at": kept["collected_at"],
            "snapshot_id": snapshot_id,
            "route_id": kept["route_id"],
            "carrier_iata": kept["carrier_iata"],
            "travel_date": kept["travel_date"],
            "advance_days": kept["advance_days"],
            "dep_hour_bucket": kept["dep_hour_bucket"],
            "stops": kept["stops"],
            "base_fare": kept["base_fare"],
            "taxes": kept["taxes"],
            "total_fare": kept["total_fare"],
            "is_outlier": kept["is_outlier"],
            "outlier_rule": kept["outlier_rule"],
            "is_imputed": False,
            "imputation_method": None,
        }
    )
    result["quality_vector"] = build_quality_vector(kept)
    return result


def _imputed_to_clean_shape(imputed: pd.DataFrame, snapshot_id: str) -> pd.DataFrame:
    if imputed.empty:
        return pd.DataFrame(columns=list(CLEAN_COLUMNS))
    result = pd.DataFrame(
        {
            "quote_id": None,
            "quote_collected_at": None,
            "snapshot_id": snapshot_id,
            "route_id": imputed["route_id"],
            "carrier_iata": imputed["carrier_iata"],
            "travel_date": imputed["travel_date"],
            "advance_days": imputed["advance_days"],
            "dep_hour_bucket": None,  # unknown for an imputed row; caller must backfill
            "stops": None,  # unknown for an imputed row; caller must backfill
            "base_fare": None,  # only total_fare is imputed, never a fabricated split
            "taxes": None,
            "total_fare": imputed["total_fare"],
            "is_outlier": False,
            "outlier_rule": None,
            "is_imputed": imputed["is_imputed"],
            "imputation_method": imputed["imputation_method"],
        }
    )
    quality_source = pd.DataFrame(
        {
            "stops": pd.Series(None, index=imputed.index, dtype="object"),
            "dep_hour_bucket": pd.Series(None, index=imputed.index, dtype="object"),
            "refundable": pd.Series(None, index=imputed.index, dtype="object"),
            "baggage_included": pd.Series(None, index=imputed.index, dtype="object"),
            "carrier_type": imputed["carrier_type"],
        }
    )
    result["quality_vector"] = build_quality_vector(quality_source)
    return result


__all__ = ["CLEAN_COLUMNS", "CleanResult", "clean_quotes"]
