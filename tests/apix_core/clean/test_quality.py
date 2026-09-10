"""Stage 5 — the hedonic quality vector."""

from __future__ import annotations

import pandas as pd
import pytest

from apix_core.clean.quality import build_quality_vector


def _quotes(**overrides: list[object]) -> pd.DataFrame:
    base = {
        "stops": [0, 1],
        "dep_hour_bucket": [7, 21],
        "refundable": [True, False],
        "baggage_included": [True, False],
        "carrier_type": ["FSC", "LCC"],
    }
    base.update(overrides)
    return pd.DataFrame(base)


class TestBuildQualityVector:
    def test_vector_carries_every_required_field(self) -> None:
        out = build_quality_vector(_quotes())
        vector = out.iloc[0]
        for key in ("stops", "dep_hour_bucket", "refundable", "baggage_included", "carrier_type"):
            assert key in vector

    def test_values_round_trip_correctly(self) -> None:
        out = build_quality_vector(_quotes())
        vector = out.iloc[0]
        assert vector == {
            "stops": 0,
            "dep_hour_bucket": 7,
            "refundable": True,
            "baggage_included": True,
            "carrier_type": "FSC",
            "aircraft": None,
            "fare_split": None,
        }

    def test_missing_values_become_none_not_nan(self) -> None:
        quotes = _quotes(stops=[None, 1], carrier_type=[None, "LCC"])
        out = build_quality_vector(quotes)
        assert out.iloc[0]["stops"] is None
        assert out.iloc[0]["carrier_type"] is None

    def test_dep_hour_falls_back_to_dep_datetime_local(self) -> None:
        quotes = _quotes().drop(columns=["dep_hour_bucket"])
        quotes["dep_datetime_local"] = ["2026-09-10 07:30", "2026-09-10 21:15"]
        out = build_quality_vector(quotes)
        assert out.iloc[0]["dep_hour_bucket"] == 7
        assert out.iloc[1]["dep_hour_bucket"] == 21

    def test_aircraft_and_fare_split_are_included_when_present(self) -> None:
        quotes = _quotes()
        quotes["aircraft"] = ["A320", None]
        quotes["fare_split_source"] = ["reported", "derived"]
        out = build_quality_vector(quotes)
        assert out.iloc[0]["aircraft"] == "A320"
        assert out.iloc[0]["fare_split"] == "reported"
        assert out.iloc[1]["aircraft"] is None
        assert out.iloc[1]["fare_split"] == "derived"

    def test_missing_required_column_raises(self) -> None:
        quotes = _quotes().drop(columns=["carrier_type"])
        with pytest.raises(ValueError, match="missing required columns"):
            build_quality_vector(quotes)

    def test_no_dep_hour_source_at_all_raises(self) -> None:
        quotes = _quotes().drop(columns=["dep_hour_bucket"])
        with pytest.raises(ValueError, match="dep_hour_bucket"):
            build_quality_vector(quotes)
