"""The aggregation hierarchy: elementary cell -> route -> national, plus sub-indices.

Worked example, two routes each with two advance windows:

    DEL-BOM: AP00_03 -> index=1.10, n=100, coverage=90
             AP04_07 -> index=1.05, n= 50, coverage=80
    BOM-DEL: AP00_03 -> index=0.95, n= 30, coverage=70
             AP04_07 -> index=1.00, n= 20, coverage=100

    booking_profile weights: AP00_03=0.6, AP04_07=0.4 (already sum to 1, both present)

    route(DEL-BOM) = exp(0.6*ln(1.10) + 0.4*ln(1.05)) = 1.0797204592
    route(BOM-DEL) = exp(0.6*ln(0.95) + 0.4*ln(1.00)) = 0.9696927826
    n_quotes(DEL-BOM) = 100+50 = 150
    coverage(DEL-BOM) = (100*90 + 50*80)/150 = 13000/150 = 86.6666666667  (quotes-weighted)
    n_quotes(BOM-DEL) = 30+20 = 50
    coverage(BOM-DEL) = (30*70 + 20*100)/50 = 4100/50 = 82.0

    dgca_pax_share: DEL-BOM=0.7, BOM-DEL=0.3

    national = exp(0.7*ln(1.0797204592) + 0.3*ln(0.9696927826)) = 1.0454618280
    n_quotes(national) = 150+50 = 200
    coverage(national) = (150*86.6666666667 + 50*82.0)/200 = 17100/200 = 85.5
"""

from __future__ import annotations

import pandas as pd
import pytest

from apix_core.index.aggregate import (
    national_index,
    route_index,
    sub_index_by,
    weighted_geometric_rollup,
)

ELEMENTARY = pd.DataFrame(
    [
        {
            "route_code": "DEL-BOM",
            "advance_window": "AP00_03",
            "carrier_type": "LCC",
            "index_value": 1.10,
            "n_quotes": 100,
            "coverage_pct": 90.0,
        },
        {
            "route_code": "DEL-BOM",
            "advance_window": "AP04_07",
            "carrier_type": "LCC",
            "index_value": 1.05,
            "n_quotes": 50,
            "coverage_pct": 80.0,
        },
        {
            "route_code": "BOM-DEL",
            "advance_window": "AP00_03",
            "carrier_type": "FSC",
            "index_value": 0.95,
            "n_quotes": 30,
            "coverage_pct": 70.0,
        },
        {
            "route_code": "BOM-DEL",
            "advance_window": "AP04_07",
            "carrier_type": "FSC",
            "index_value": 1.00,
            "n_quotes": 20,
            "coverage_pct": 100.0,
        },
    ]
)

BOOKING_PROFILE_WEIGHTS = {"AP00_03": 0.6, "AP04_07": 0.4}
DGCA_PAX_SHARE = {"DEL-BOM": 0.7, "BOM-DEL": 0.3}


class TestRouteIndexGolden:
    def test_route_levels(self) -> None:
        result = route_index(ELEMENTARY, BOOKING_PROFILE_WEIGHTS).set_index("route_code")
        assert result.loc["DEL-BOM", "index_value"] == pytest.approx(1.0797204592, abs=1e-9)
        assert result.loc["BOM-DEL", "index_value"] == pytest.approx(0.9696927826, abs=1e-9)

    def test_n_quotes_sums_exactly(self) -> None:
        result = route_index(ELEMENTARY, BOOKING_PROFILE_WEIGHTS).set_index("route_code")
        assert result.loc["DEL-BOM", "n_quotes"] == 150
        assert result.loc["BOM-DEL", "n_quotes"] == 50

    def test_coverage_is_quotes_weighted(self) -> None:
        result = route_index(ELEMENTARY, BOOKING_PROFILE_WEIGHTS).set_index("route_code")
        assert result.loc["DEL-BOM", "coverage_pct"] == pytest.approx(86.6666666667, abs=1e-6)
        assert result.loc["BOM-DEL", "coverage_pct"] == pytest.approx(82.0, abs=1e-9)

    def test_missing_window_weight_is_rejected(self) -> None:
        bad = pd.concat(
            [
                ELEMENTARY,
                pd.DataFrame(
                    [
                        {
                            "route_code": "DEL-BOM",
                            "advance_window": "AP61_90",
                            "carrier_type": "LCC",
                            "index_value": 1.2,
                            "n_quotes": 5,
                            "coverage_pct": 50.0,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        with pytest.raises(ValueError, match="AP61_90"):
            route_index(bad, BOOKING_PROFILE_WEIGHTS)


class TestNationalIndexGolden:
    def test_national_level(self) -> None:
        route_level = route_index(ELEMENTARY, BOOKING_PROFILE_WEIGHTS)
        national, excluded = national_index(route_level, DGCA_PAX_SHARE)
        assert excluded == []
        assert national.loc[0, "index_value"] == pytest.approx(1.0454618280, abs=1e-9)

    def test_national_n_quotes_and_coverage(self) -> None:
        route_level = route_index(ELEMENTARY, BOOKING_PROFILE_WEIGHTS)
        national, _ = national_index(route_level, DGCA_PAX_SHARE)
        assert national.loc[0, "n_quotes"] == 200
        assert national.loc[0, "coverage_pct"] == pytest.approx(85.5, abs=1e-9)

    def test_a_route_with_no_configured_weight_is_excluded_not_guessed(self) -> None:
        route_level = route_index(ELEMENTARY, BOOKING_PROFILE_WEIGHTS)
        partial_weights = {"DEL-BOM": 1.0}  # BOM-DEL deliberately has no share
        national, excluded = national_index(route_level, partial_weights)
        assert excluded == ["BOM-DEL"]
        # With only DEL-BOM weighted, the national number is exactly DEL-BOM's index.
        assert national.loc[0, "index_value"] == pytest.approx(1.0797204592, abs=1e-9)

    def test_no_route_weighted_is_a_hard_failure(self) -> None:
        route_level = route_index(ELEMENTARY, BOOKING_PROFILE_WEIGHTS)
        with pytest.raises(ValueError, match="dgca_pax_share"):
            national_index(route_level, {})


class TestSubIndexBy:
    def test_breakdown_by_carrier_type(self) -> None:
        result = sub_index_by(ELEMENTARY, "carrier_type", "n_quotes").set_index("carrier_type")
        # LCC = DEL-BOM's two cells, weighted by n_quotes (100, 50).
        expected_lcc = (1.10 ** (100 / 150)) * (1.05 ** (50 / 150))
        assert result.loc["LCC", "index_value"] == pytest.approx(expected_lcc, abs=1e-9)
        assert result.loc["LCC", "n_quotes"] == 150
        assert result.loc["FSC", "n_quotes"] == 50

    def test_breakdown_by_advance_window(self) -> None:
        result = sub_index_by(ELEMENTARY, "advance_window", "n_quotes").set_index("advance_window")
        assert set(result.index) == {"AP00_03", "AP04_07"}
        assert result.loc["AP00_03", "n_quotes"] == 130  # 100 + 30


class TestWeightedGeometricRollupProperties:
    def test_identical_values_roll_up_to_exactly_that_value(self) -> None:
        df = pd.DataFrame(
            {
                "group": ["g", "g", "g"],
                "index_value": [1.234, 1.234, 1.234],
                "n_quotes": [10, 20, 30],
                "coverage_pct": [100.0, 50.0, 0.0],
            }
        )
        result = weighted_geometric_rollup(df, ["group"], "n_quotes")
        assert result.loc[0, "index_value"] == pytest.approx(1.234, abs=1e-12)

    def test_n_quotes_always_sums(self) -> None:
        df = pd.DataFrame(
            {
                "group": ["g", "g"],
                "index_value": [1.1, 0.9],
                "n_quotes": [7, 13],
                "coverage_pct": [100.0, 100.0],
            }
        )
        result = weighted_geometric_rollup(df, ["group"], "n_quotes")
        assert result.loc[0, "n_quotes"] == 20

    def test_full_coverage_children_roll_up_to_full_coverage(self) -> None:
        df = pd.DataFrame(
            {
                "group": ["g", "g"],
                "index_value": [1.1, 0.9],
                "n_quotes": [7, 13],
                "coverage_pct": [100.0, 100.0],
            }
        )
        result = weighted_geometric_rollup(df, ["group"], "n_quotes")
        assert result.loc[0, "coverage_pct"] == pytest.approx(100.0)

    def test_empty_group_collapses_to_a_single_row(self) -> None:
        result = weighted_geometric_rollup(ELEMENTARY, [], "n_quotes")
        assert len(result) == 1
        assert "route_code" not in result.columns


class TestValidation:
    def test_non_positive_index_value_rejected(self) -> None:
        df = pd.DataFrame(
            {"group": ["g"], "index_value": [0.0], "n_quotes": [1], "coverage_pct": [100.0]}
        )
        with pytest.raises(ValueError, match="positive"):
            weighted_geometric_rollup(df, ["group"], "n_quotes")

    def test_zero_total_weight_rejected(self) -> None:
        df = pd.DataFrame(
            {
                "group": ["g", "g"],
                "index_value": [1.0, 1.0],
                "n_quotes": [0, 0],
                "coverage_pct": [0.0, 0.0],
            }
        )
        with pytest.raises(ValueError, match="weights sum to zero"):
            weighted_geometric_rollup(df, ["group"], "n_quotes")

    def test_missing_columns_rejected(self) -> None:
        with pytest.raises(ValueError, match="missing required columns"):
            weighted_geometric_rollup(pd.DataFrame({"group": ["g"]}), ["group"], "n_quotes")

    def test_empty_input_rejected(self) -> None:
        empty = pd.DataFrame(columns=["group", "index_value", "n_quotes", "coverage_pct"])
        with pytest.raises(ValueError, match="at least one row"):
            weighted_geometric_rollup(empty, ["group"], "n_quotes")

    def test_negative_n_quotes_rejected(self) -> None:
        df = pd.DataFrame(
            {"group": ["g"], "index_value": [1.0], "n_quotes": [-1], "coverage_pct": [50.0]}
        )
        with pytest.raises(ValueError, match="n_quotes must be non-negative"):
            weighted_geometric_rollup(df, ["group"], "n_quotes")

    def test_out_of_range_coverage_pct_rejected(self) -> None:
        df = pd.DataFrame(
            {"group": ["g"], "index_value": [1.0], "n_quotes": [1], "coverage_pct": [150.0]}
        )
        with pytest.raises(ValueError, match=r"coverage_pct must be within \[0, 100\]"):
            weighted_geometric_rollup(df, ["group"], "n_quotes")

    def test_negative_weight_column_rejected(self) -> None:
        df = pd.DataFrame(
            {
                "group": ["g", "g"],
                "index_value": [1.0, 1.1],
                "n_quotes": [1, 1],
                "coverage_pct": [50.0, 50.0],
                "weight": [-1.0, 1.0],
            }
        )
        with pytest.raises(ValueError, match="weight must be non-negative"):
            weighted_geometric_rollup(df, ["group"], "weight")

    def test_route_index_reports_missing_required_columns(self) -> None:
        with pytest.raises(ValueError, match="route_index: missing required columns"):
            route_index(pd.DataFrame({"index_value": [1.0]}), BOOKING_PROFILE_WEIGHTS)

    def test_national_index_requires_route_code(self) -> None:
        with pytest.raises(ValueError, match="national_index: route_level must have"):
            national_index(pd.DataFrame({"index_value": [1.0]}), DGCA_PAX_SHARE)
