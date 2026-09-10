"""Stage 2 — fare decomposition.

Sources differ in how much of the fare they itemise. Some publish
base + taxes + UDF (+ convenience fee) directly; others show only ``total_fare``. For
the latter, this module derives the missing components algebraically from the airport's
published user development fee (UDF) and the published tax rate — it never guesses a
split. When the components cannot be derived (the UDF for the origin airport is not in
the reference table, or the derivation would imply a negative base fare), the row is
left undetermined rather than filled with a plausible-looking number.

Every row is labelled with how its split was obtained (``fare_split_source``:
``"reported"``, ``"derived"`` or ``"undetermined"``) so the quality vector — and anyone
auditing a published number back to its source — can see which. Pure function: no
database access, no I/O.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Literal

import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Mapping

FareSplitSource = Literal["reported", "derived", "undetermined"]

REQUIRED_COLUMNS = (
    "id",
    "origin_iata",
    "base_fare",
    "taxes",
    "udf",
    "convenience_fee",
    "total_fare",
)

_TWO_PLACES = Decimal("0.01")
_CONSISTENCY_TOLERANCE = Decimal("0.01")


def decompose_fares(
    quotes: pd.DataFrame,
    airport_udf: Mapping[str, Decimal],
    tax_rate: float,
) -> pd.DataFrame:
    """Return ``quotes`` with base/taxes/udf/convenience_fee filled in where derivable.

    Adds two columns:

    * ``fare_split_source`` — ``"reported"`` (all of base_fare, taxes and udf were
      already present), ``"derived"`` (this function computed them from total_fare) or
      ``"undetermined"`` (derivation was not possible; the money columns are left as
      they arrived, which for a non-itemising source means still null).
    * ``component_sum_consistent`` — for ``"reported"`` rows, whether
      base + taxes + udf + convenience_fee actually equals total_fare (within a cent);
      ``True`` by construction for ``"derived"`` rows; ``pd.NA`` for ``"undetermined"``.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in quotes.columns]
    if missing:
        raise ValueError(f"decompose_fares: missing required columns: {missing}")
    if not (0 <= tax_rate <= 1):
        raise ValueError(f"tax_rate must be within [0, 1], got {tax_rate}")

    result = quotes.copy()
    if result.empty:
        result["fare_split_source"] = pd.Series(dtype="object")
        result["component_sum_consistent"] = pd.Series(dtype="object")
        return result

    tax_rate_dec = Decimal(str(tax_rate))
    one_plus_tax = Decimal("1") + tax_rate_dec

    is_itemized = result["base_fare"].notna() & result["taxes"].notna() & result["udf"].notna()

    fare_split_source = pd.Series("undetermined", index=result.index, dtype="object")
    component_sum_consistent = pd.Series(pd.NA, index=result.index, dtype="object")

    # --- reported: itemised at the source ---------------------------------------
    fare_split_source.loc[is_itemized] = "reported"
    fee_or_zero = result["convenience_fee"].where(result["convenience_fee"].notna(), Decimal("0"))
    for idx in result.index[is_itemized]:
        component_sum = (
            result.at[idx, "base_fare"]
            + result.at[idx, "taxes"]
            + result.at[idx, "udf"]
            + fee_or_zero.at[idx]
        )
        component_sum_consistent.at[idx] = (
            abs(component_sum - result.at[idx, "total_fare"]) <= _CONSISTENCY_TOLERANCE
        )

    # --- derive the rest from total_fare, the airport UDF table and the tax rate ---
    to_derive = result.index[~is_itemized]
    origin_udf = result.loc[to_derive, "origin_iata"].map(airport_udf)

    for idx in to_derive:
        udf_val = origin_udf.at[idx]
        if pd.isna(udf_val):
            continue  # no UDF on file for this airport — stays "undetermined"
        fee_val = fee_or_zero.at[idx]
        base_val = ((result.at[idx, "total_fare"] - udf_val - fee_val) / one_plus_tax).quantize(
            _TWO_PLACES
        )
        if base_val <= 0:
            continue  # implausible derivation — recorded, not silently accepted
        taxes_val = (base_val * tax_rate_dec).quantize(_TWO_PLACES)
        result.at[idx, "base_fare"] = base_val
        result.at[idx, "taxes"] = taxes_val
        result.at[idx, "udf"] = udf_val
        result.at[idx, "convenience_fee"] = fee_val
        fare_split_source.at[idx] = "derived"
        component_sum_consistent.at[idx] = True

    result["fare_split_source"] = fare_split_source
    result["component_sum_consistent"] = component_sum_consistent
    return result


__all__ = ["FareSplitSource", "decompose_fares"]
