"""Stage 5 — quality vector construction.

Builds the JSONB ``quality_vector`` the hedonic model reads from ``fare_quote_clean``:
one self-contained characteristics blob per row, independent of which characteristics
also happen to be first-class columns elsewhere (``stops`` and the departure-hour
bucket are — see ``config/method.yaml`` — but the hedonic layer consumes them from here
regardless, so the vector is never partial). It also carries ``fare_split`` — whether
stage 2 reported or derived the fare's decomposition — so an auditor can see how a row's
components were obtained without cross-referencing a separate column.

Pure function: no database access, no I/O.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

REQUIRED_COLUMNS = ("stops", "refundable", "baggage_included", "carrier_type")


def build_quality_vector(
    quotes: pd.DataFrame,
    dep_hour_column: str = "dep_hour_bucket",
    aircraft_column: str = "aircraft",
    fare_split_column: str = "fare_split_source",
) -> pd.Series:
    """Return one quality-vector ``dict`` per row of ``quotes``, as a ``pd.Series``.

    ``dep_hour_column`` is read directly if present; otherwise it is derived from
    ``dep_datetime_local``. ``aircraft`` and ``fare_split`` are included when their
    source columns are present, and ``None`` (never guessed) when they are not.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in quotes.columns]
    if missing:
        raise ValueError(f"build_quality_vector: missing required columns: {missing}")

    if dep_hour_column in quotes.columns:
        dep_hour = quotes[dep_hour_column]
    elif "dep_datetime_local" in quotes.columns:
        dep_hour = pd.to_datetime(quotes["dep_datetime_local"]).dt.hour
    else:
        raise ValueError(
            "build_quality_vector: need a dep_hour_bucket column or dep_datetime_local"
        )

    aircraft = quotes[aircraft_column] if aircraft_column in quotes.columns else _all_null(quotes)
    fare_split = (
        quotes[fare_split_column] if fare_split_column in quotes.columns else _all_null(quotes)
    )

    vectors: list[dict[str, Any]] = []
    for stops, hour, refundable, baggage, carrier_type, ac, split in zip(
        quotes["stops"],
        dep_hour,
        quotes["refundable"],
        quotes["baggage_included"],
        quotes["carrier_type"],
        aircraft,
        fare_split,
        strict=True,
    ):
        vectors.append(
            {
                "stops": _maybe_int(stops),
                "dep_hour_bucket": _maybe_int(hour),
                "refundable": _maybe_bool(refundable),
                "baggage_included": _maybe_bool(baggage),
                "carrier_type": _maybe_str(carrier_type),
                "aircraft": _maybe_str(ac),
                "fare_split": _maybe_str(split),
            }
        )
    return pd.Series(vectors, index=quotes.index, dtype="object")


def _all_null(quotes: pd.DataFrame) -> pd.Series:
    return pd.Series(None, index=quotes.index, dtype="object")


def _maybe_int(value: object) -> int | None:
    return None if pd.isna(value) else int(value)  # type: ignore[call-overload]


def _maybe_bool(value: object) -> bool | None:
    return None if pd.isna(value) else bool(value)


def _maybe_str(value: object) -> str | None:
    return None if pd.isna(value) else str(value)


__all__ = ["REQUIRED_COLUMNS", "build_quality_vector"]
