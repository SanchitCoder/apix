"""Stage 1 — the same flight, seen by several sources, shares a flight_key."""

from __future__ import annotations

import pandas as pd
import pytest

from apix_core.clean.dedup import assign_flight_key


def _quotes(**overrides: list[object]) -> pd.DataFrame:
    base = {
        "id": ["q1", "q2", "q3", "q4"],
        "carrier_iata": ["AI", "AI", "AI", "6E"],
        "flight_number": ["AI101", "AI101", "AI101", "6E202"],
        "travel_date": ["2026-09-10"] * 4,
        "dep_datetime_local": [
            "2026-09-10 07:00",
            "2026-09-10 07:05",
            "2026-09-10 21:00",
            "2026-09-10 07:00",
        ],
    }
    base.update(overrides)
    return pd.DataFrame(base)


class TestAssignFlightKey:
    def test_same_flight_within_tolerance_shares_a_key(self) -> None:
        out = assign_flight_key(_quotes(), dep_time_tolerance_minutes=15)
        assert out.loc[out["id"] == "q1", "flight_key"].item()
        assert (
            out.loc[out["id"] == "q1", "flight_key"].item()
            == out.loc[out["id"] == "q2", "flight_key"].item()
        )

    def test_different_departure_time_gets_a_different_key(self) -> None:
        out = assign_flight_key(_quotes(), dep_time_tolerance_minutes=15)
        first = out.loc[out["id"] == "q1", "flight_key"].item()
        evening = out.loc[out["id"] == "q3", "flight_key"].item()
        assert first != evening

    def test_different_carrier_gets_a_different_key(self) -> None:
        out = assign_flight_key(_quotes(), dep_time_tolerance_minutes=15)
        ai = out.loc[out["id"] == "q1", "flight_key"].item()
        six_e = out.loc[out["id"] == "q4", "flight_key"].item()
        assert ai != six_e

    def test_no_row_is_dropped(self) -> None:
        quotes = _quotes()
        out = assign_flight_key(quotes, dep_time_tolerance_minutes=15)
        assert len(out) == len(quotes)
        assert set(out["id"]) == set(quotes["id"])

    def test_result_is_deterministic(self) -> None:
        quotes = _quotes()
        first = assign_flight_key(quotes, dep_time_tolerance_minutes=15)
        second = assign_flight_key(quotes, dep_time_tolerance_minutes=15)
        pd.testing.assert_series_equal(first["flight_key"], second["flight_key"])

    def test_zero_tolerance_only_merges_identical_timestamps(self) -> None:
        out = assign_flight_key(_quotes(), dep_time_tolerance_minutes=0)
        assert (
            out.loc[out["id"] == "q1", "flight_key"].item()
            != out.loc[out["id"] == "q2", "flight_key"].item()
        )

    def test_empty_input_returns_empty_with_flight_key_column(self) -> None:
        empty = _quotes().iloc[0:0]
        out = assign_flight_key(empty, dep_time_tolerance_minutes=15)
        assert out.empty
        assert "flight_key" in out.columns

    def test_missing_required_column_raises(self) -> None:
        quotes = _quotes().drop(columns=["carrier_iata"])
        with pytest.raises(ValueError, match="missing required columns"):
            assign_flight_key(quotes, dep_time_tolerance_minutes=15)

    def test_negative_tolerance_raises(self) -> None:
        with pytest.raises(ValueError, match="tolerance"):
            assign_flight_key(_quotes(), dep_time_tolerance_minutes=-1)
