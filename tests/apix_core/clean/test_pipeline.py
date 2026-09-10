"""clean_quotes() wires the five stages together into one fare_quote_clean-shaped result."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from apix_core.clean.pipeline import CLEAN_COLUMNS, clean_quotes
from apix_core.config import load_cleaning

if TYPE_CHECKING:
    from apix_core.config.cleaning import CleaningConfig

CARRIER_TYPE = {"AI": "FSC", "6E": "LCC"}
UDF_REF = {"DEL": Decimal("100")}


@pytest.fixture(scope="module")
def cleaning_config(config_dir) -> CleaningConfig:
    return load_cleaning(config_dir)


def _quotes() -> pd.DataFrame:
    def qid() -> str:
        return str(uuid.uuid4())

    rows = []
    for src, carrier, flight, base, taxes, udf in (
        ("s1", "AI", "AI101", Decimal("4000"), Decimal("200"), Decimal("100")),
        ("s2", "AI", "AI101", Decimal("4000"), Decimal("200"), Decimal("100")),
        ("s1", "6E", "6E202", None, None, None),
    ):
        rows.append(
            {
                "id": qid(),
                "source_id": src,
                "collected_at": pd.Timestamp("2026-09-01 06:00"),
                "route_id": "DEL-BOM",
                "carrier_iata": carrier,
                "flight_number": flight,
                "origin_iata": "DEL",
                "dep_datetime_local": pd.Timestamp("2026-09-06 07:00"),
                "travel_date": pd.Timestamp("2026-09-06").date(),
                "advance_days": 5,
                "stops": 0,
                "refundable": True,
                "baggage_included": True,
                "base_fare": base,
                "taxes": taxes,
                "udf": udf,
                "convenience_fee": Decimal("0"),
                "total_fare": Decimal("4300") if carrier == "AI" else Decimal("4800"),
            }
        )
    return pd.DataFrame(rows)


def _expected_cells() -> pd.DataFrame:
    rows = []
    for src in ("s1", "s2"):
        for carrier, flight in (("AI", "AI101"), ("6E", "6E202")):
            rows.append(
                {
                    "source_id": src,
                    "route_id": "DEL-BOM",
                    "carrier_iata": carrier,
                    "flight_number": flight,
                    "advance_days": 5,
                    "query_date": pd.Timestamp("2026-09-01").date(),
                    "travel_date": pd.Timestamp("2026-09-06").date(),
                }
            )
    return pd.DataFrame(rows)


def _collection_runs() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_id": ["s1", "s2"],
            "route_id": ["DEL-BOM", "DEL-BOM"],
            "query_date": [pd.Timestamp("2026-09-01").date()] * 2,
            "status": ["SUCCEEDED", "SUCCEEDED"],
        }
    )


class TestCleanQuotes:
    def test_output_has_the_fare_quote_clean_shape(self, cleaning_config: CleaningConfig) -> None:
        result = clean_quotes(
            _quotes(),
            _expected_cells(),
            _collection_runs(),
            CARRIER_TYPE,
            UDF_REF,
            snapshot_id="snap1",
            config=cleaning_config,
        )
        assert list(result.clean.columns) == list(CLEAN_COLUMNS)

    def test_observed_rows_carry_their_source_lineage(
        self, cleaning_config: CleaningConfig
    ) -> None:
        result = clean_quotes(
            _quotes(),
            _expected_cells(),
            _collection_runs(),
            CARRIER_TYPE,
            UDF_REF,
            snapshot_id="snap1",
            config=cleaning_config,
        )
        observed = result.clean[~result.clean["is_imputed"]]
        assert observed["quote_id"].notna().all()
        assert observed["quote_collected_at"].notna().all()

    def test_non_itemising_source_gets_a_derived_split(
        self, cleaning_config: CleaningConfig
    ) -> None:
        result = clean_quotes(
            _quotes(),
            _expected_cells(),
            _collection_runs(),
            CARRIER_TYPE,
            UDF_REF,
            snapshot_id="snap1",
            config=cleaning_config,
        )
        six_e_row = result.clean[result.clean["carrier_iata"] == "6E"].iloc[0]
        assert six_e_row["quality_vector"]["fare_split"] == "derived"
        assert six_e_row["base_fare"] is not None

    def test_missing_cell_is_imputed_or_left_unresolved_never_silently_dropped(
        self, cleaning_config: CleaningConfig
    ) -> None:
        result = clean_quotes(
            _quotes(),
            _expected_cells(),
            _collection_runs(),
            CARRIER_TYPE,
            UDF_REF,
            snapshot_id="snap1",
            config=cleaning_config,
        )
        # s2/6E202 is expected but never observed; either imputed into `clean` or
        # reported in `unresolved` — accounted for either way, per docs/imputation.md.
        imputed_count = int(result.clean["is_imputed"].sum())
        assert imputed_count + len(result.unresolved) >= 1

    def test_imputed_rows_never_carry_a_fabricated_base_fare(
        self, cleaning_config: CleaningConfig
    ) -> None:
        result = clean_quotes(
            _quotes(),
            _expected_cells(),
            _collection_runs(),
            CARRIER_TYPE,
            UDF_REF,
            snapshot_id="snap1",
            config=cleaning_config,
        )
        imputed = result.clean[result.clean["is_imputed"]]
        assert imputed["base_fare"].isna().all()

    def test_every_imputed_row_has_a_method(self, cleaning_config: CleaningConfig) -> None:
        result = clean_quotes(
            _quotes(),
            _expected_cells(),
            _collection_runs(),
            CARRIER_TYPE,
            UDF_REF,
            snapshot_id="snap1",
            config=cleaning_config,
        )
        imputed = result.clean[result.clean["is_imputed"]]
        assert imputed["imputation_method"].notna().all()

    def test_coverage_and_snapshot_id_are_populated(self, cleaning_config: CleaningConfig) -> None:
        result = clean_quotes(
            _quotes(),
            _expected_cells(),
            _collection_runs(),
            CARRIER_TYPE,
            UDF_REF,
            snapshot_id="snap1",
            config=cleaning_config,
        )
        assert not result.coverage.empty
        assert (result.clean["snapshot_id"] == "snap1").all()

    def test_malformed_input_row_is_quarantined_and_excluded_from_clean(
        self, cleaning_config: CleaningConfig
    ) -> None:
        quotes = _quotes()
        quotes.loc[0, "total_fare"] = Decimal("-1")
        result = clean_quotes(
            quotes,
            _expected_cells(),
            _collection_runs(),
            CARRIER_TYPE,
            UDF_REF,
            snapshot_id="snap1",
            config=cleaning_config,
        )
        assert len(result.quarantined) == 1
        assert quotes.loc[0, "id"] not in set(result.clean["quote_id"].dropna())
