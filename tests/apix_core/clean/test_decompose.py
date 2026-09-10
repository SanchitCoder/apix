"""Stage 2 — fare decomposition: reported vs derived vs undetermined."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from apix_core.clean.decompose import decompose_fares

UDF_REF = {"DEL": Decimal("100"), "BOM": Decimal("200")}


def _quotes(**overrides: list[object]) -> pd.DataFrame:
    base = {
        "id": ["q1", "q2", "q3", "q4"],
        "origin_iata": ["DEL", "DEL", "BOM", "GOI"],
        "base_fare": [Decimal("3000"), None, None, None],
        "taxes": [Decimal("150"), None, None, None],
        "udf": [Decimal("100"), None, None, None],
        "convenience_fee": [Decimal("0"), Decimal("349"), None, None],
        "total_fare": [Decimal("3250"), Decimal("5000"), Decimal("4500"), Decimal("6000")],
    }
    base.update(overrides)
    return pd.DataFrame(base)


class TestReported:
    def test_itemised_row_is_left_untouched_and_marked_reported(self) -> None:
        out = decompose_fares(_quotes(), UDF_REF, tax_rate=0.05)
        row = out.loc[out["id"] == "q1"].iloc[0]
        assert row["fare_split_source"] == "reported"
        assert row["base_fare"] == Decimal("3000")

    def test_consistent_components_are_flagged_true(self) -> None:
        out = decompose_fares(_quotes(), UDF_REF, tax_rate=0.05)
        row = out.loc[out["id"] == "q1"].iloc[0]
        assert row["component_sum_consistent"] is True

    def test_inconsistent_components_are_flagged_false(self) -> None:
        quotes = _quotes()
        quotes.loc[quotes["id"] == "q1", "total_fare"] = Decimal("999999")
        out = decompose_fares(quotes, UDF_REF, tax_rate=0.05)
        row = out.loc[out["id"] == "q1"].iloc[0]
        assert row["fare_split_source"] == "reported"
        assert row["component_sum_consistent"] is False


class TestDerived:
    def test_total_only_source_is_derived_from_udf_and_tax_rate(self) -> None:
        out = decompose_fares(_quotes(), UDF_REF, tax_rate=0.05)
        row = out.loc[out["id"] == "q2"].iloc[0]
        assert row["fare_split_source"] == "derived"
        # total=5000, udf=100 (DEL), fee=349 -> base=(5000-100-349)/1.05
        expected_base = (
            (Decimal("5000") - Decimal("100") - Decimal("349")) / Decimal("1.05")
        ).quantize(Decimal("0.01"))
        assert row["base_fare"] == expected_base
        assert row["taxes"] == (expected_base * Decimal("0.05")).quantize(Decimal("0.01"))

    def test_derived_components_are_always_consistent(self) -> None:
        out = decompose_fares(_quotes(), UDF_REF, tax_rate=0.05)
        row = out.loc[out["id"] == "q2"].iloc[0]
        assert row["component_sum_consistent"] is True

    def test_missing_convenience_fee_is_treated_as_zero(self) -> None:
        out = decompose_fares(_quotes(), UDF_REF, tax_rate=0.05)
        row = out.loc[out["id"] == "q3"].iloc[0]  # BOM, no convenience_fee
        assert row["fare_split_source"] == "derived"
        expected_base = (Decimal("4500") - Decimal("200")) / Decimal("1.05")
        assert float(row["base_fare"]) == pytest.approx(float(expected_base), abs=0.01)


class TestUndetermined:
    def test_unknown_airport_udf_is_undetermined(self) -> None:
        out = decompose_fares(_quotes(), UDF_REF, tax_rate=0.05)
        row = out.loc[out["id"] == "q4"].iloc[0]  # GOI, not in UDF_REF
        assert row["fare_split_source"] == "undetermined"
        assert pd.isna(row["base_fare"])
        assert pd.isna(row["component_sum_consistent"])

    def test_negative_derived_base_fare_is_undetermined_not_guessed(self) -> None:
        quotes = _quotes()
        quotes.loc[quotes["id"] == "q2", "total_fare"] = Decimal("50")  # less than udf + fee
        out = decompose_fares(quotes, UDF_REF, tax_rate=0.05)
        row = out.loc[out["id"] == "q2"].iloc[0]
        assert row["fare_split_source"] == "undetermined"
        assert pd.isna(row["base_fare"])


class TestValidation:
    def test_missing_required_column_raises(self) -> None:
        quotes = _quotes().drop(columns=["udf"])
        with pytest.raises(ValueError, match="missing required columns"):
            decompose_fares(quotes, UDF_REF, tax_rate=0.05)

    def test_tax_rate_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="tax_rate"):
            decompose_fares(_quotes(), UDF_REF, tax_rate=1.5)

    def test_empty_input_returns_empty_with_new_columns(self) -> None:
        empty = _quotes().iloc[0:0]
        out = decompose_fares(empty, UDF_REF, tax_rate=0.05)
        assert out.empty
        assert {"fare_split_source", "component_sum_consistent"} <= set(out.columns)
