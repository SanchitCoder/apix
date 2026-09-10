from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from apix_core.watchdog.sellout import compute_sellout_velocity


def _missing_cells(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class TestComputeSelloutVelocity:
    def test_reports_the_largest_advance_days_among_sold_out_observations(self) -> None:
        rows = [
            {
                "route_id": "r1",
                "carrier_type": "LCC",
                "advance_days": ad,
                "travel_date": date(2026, 9, 15),
                "missing_reason": "sold_out",
            }
            for ad in (3, 7, 14)
        ]
        rows.append(
            {
                "route_id": "r1",
                "carrier_type": "LCC",
                "advance_days": 30,
                "travel_date": date(2026, 9, 15),
                "missing_reason": "not_collected",
            }
        )
        result = compute_sellout_velocity(_missing_cells(rows), min_group_size=1)
        assert len(result) == 1
        assert result["earliest_sold_out_advance_days"].iloc[0] == 14
        assert result["n_sold_out_observations"].iloc[0] == 3

    def test_groups_below_min_group_size_are_dropped(self) -> None:
        rows = [
            {
                "route_id": "r1",
                "carrier_type": "LCC",
                "advance_days": 5,
                "travel_date": date(2026, 9, 15),
                "missing_reason": "sold_out",
            }
        ]
        result = compute_sellout_velocity(_missing_cells(rows), min_group_size=3)
        assert result.empty

    def test_no_sold_out_rows_gives_an_empty_result_not_an_error(self) -> None:
        rows = [
            {
                "route_id": "r1",
                "carrier_type": "LCC",
                "advance_days": 5,
                "travel_date": date(2026, 9, 15),
                "missing_reason": "not_collected",
            }
        ]
        result = compute_sellout_velocity(_missing_cells(rows))
        assert result.empty
        assert list(result.columns) == [
            "route_id",
            "carrier_type",
            "travel_date",
            "earliest_sold_out_advance_days",
            "n_sold_out_observations",
        ]

    def test_missing_columns_is_a_value_error(self) -> None:
        with pytest.raises(ValueError, match="missing required columns"):
            compute_sellout_velocity(pd.DataFrame({"route_id": ["r1"]}))
