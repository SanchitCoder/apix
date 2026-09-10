from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from apix_core.watchdog.rail import NotImplementedRailFareSource, compare_to_rail


class TestNotImplementedRailFareSource:
    def test_raises_not_implemented_error(self) -> None:
        source = NotImplementedRailFareSource()
        with pytest.raises(NotImplementedError, match="no rail fare source"):
            source.fares_for_corridor("DEL-BOM", date(2026, 9, 1))


class TestCompareToRail:
    def test_empty_rail_fares_gives_an_empty_result_not_an_error(self) -> None:
        airfare = pd.DataFrame(
            {"route_code": ["DEL-BOM"], "period": [date(2026, 9, 1)], "fare": [5000.0]}
        )
        rail_fares = pd.DataFrame(columns=["route_code", "period", "rail_fare"])
        result = compare_to_rail(airfare, rail_fares)
        assert result.empty
        assert list(result.columns) == [
            "route_code",
            "period",
            "airfare",
            "rail_fare",
            "ratio",
            "spread",
        ]

    def test_computes_ratio_and_spread(self) -> None:
        airfare = pd.DataFrame(
            {"route_code": ["DEL-BOM"], "period": [date(2026, 9, 1)], "fare": [5000.0]}
        )
        rail_fares = pd.DataFrame(
            {"route_code": ["DEL-BOM"], "period": [date(2026, 9, 1)], "rail_fare": [2000.0]}
        )
        result = compare_to_rail(airfare, rail_fares)
        assert result["ratio"].iloc[0] == pytest.approx(2.5)
        assert result["spread"].iloc[0] == pytest.approx(3000.0)

    def test_missing_airfare_columns_is_a_value_error(self) -> None:
        with pytest.raises(ValueError, match="missing required columns"):
            compare_to_rail(pd.DataFrame({"route_code": ["DEL-BOM"]}), pd.DataFrame())
