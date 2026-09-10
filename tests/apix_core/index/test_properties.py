"""Cross-cutting property tests for the index module, end to end.

Per-function invariants (time reversal, scale invariance) live alongside each
function's golden tests. This file checks the two properties the task calls out that
only make sense once several layers compose together: a flat price path publishes at
exactly the reference value (100), and unit scaling never moves any index.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from apix_core.config.method import MethodConfigFile
from apix_core.index.aggregate import national_index, route_index
from apix_core.index.elementary import jevons
from apix_core.index.multilateral import geks_tornqvist, time_product_dummy
from apix_core.index.run import run_hash, run_index
from apix_core.index.weighting import combine_advance_windows

INDEX_REFERENCE_VALUE = 100.0


def _flat_panel(n_products: int, n_periods: int, price: float = 500.0) -> pd.DataFrame:
    rows = [(t, f"P{i}", price, 1.0) for t in range(n_periods) for i in range(n_products)]
    return pd.DataFrame(rows, columns=["period", "product_id", "price", "share"])


class TestIdenticalPricesPublishAtExactlyTheReferenceValue:
    """Identical prices give exactly 100 — every layer, all the way to publication."""

    def test_elementary_jevons(self) -> None:
        prices = [500.0, 500.0, 500.0]
        assert jevons(prices, prices) * INDEX_REFERENCE_VALUE == 100.0

    def test_geks_tornqvist_over_a_flat_panel(self) -> None:
        panel = _flat_panel(n_products=4, n_periods=6)
        result = geks_tornqvist(panel, window_days=6)
        assert (result * INDEX_REFERENCE_VALUE == 100.0).all()

    def test_time_product_dummy_over_a_flat_panel(self) -> None:
        panel = _flat_panel(n_products=4, n_periods=6)
        result = time_product_dummy(panel, window_days=6)
        scaled = result * INDEX_REFERENCE_VALUE
        assert scaled.to_numpy() == pytest.approx(100.0, abs=1e-8)

    def test_combine_advance_windows(self) -> None:
        index_by_window = pd.Series({"AP00_03": 1.0, "AP04_07": 1.0, "AP08_14": 1.0})
        weights = {"AP00_03": 0.5, "AP04_07": 0.3, "AP08_14": 0.2}
        combined, coverage_pct = combine_advance_windows(index_by_window, weights)
        assert combined * INDEX_REFERENCE_VALUE == 100.0
        assert coverage_pct == 100.0

    def test_route_and_national_index(self) -> None:
        elementary = pd.DataFrame(
            [
                {
                    "route_code": route,
                    "advance_window": window,
                    "index_value": 1.0,
                    "n_quotes": 50,
                    "coverage_pct": 100.0,
                }
                for route in ("DEL-BOM", "BOM-DEL")
                for window in ("AP00_03", "AP04_07")
            ]
        )
        weights = {"AP00_03": 0.6, "AP04_07": 0.4}
        routes = route_index(elementary, weights)
        assert (routes["index_value"] * INDEX_REFERENCE_VALUE == 100.0).all()

        national, excluded = national_index(routes, {"DEL-BOM": 0.7, "BOM-DEL": 0.3})
        assert excluded == []
        assert national.loc[0, "index_value"] * INDEX_REFERENCE_VALUE == pytest.approx(
            100.0, abs=1e-9
        )

    def test_a_first_ever_run_index_publication(self) -> None:
        """run_index's first-publication path (no prior history) times
        ``index_reference_value`` is exactly 100 when the window shows no movement.
        """
        window_indices = {"national": pd.Series([1.0, 1.0, 1.0], index=[0, 1, 2])}
        published = pd.DataFrame(columns=["series_code", "period", "value"])
        coverage = {"national": (900, 100.0)}
        config = MethodConfigFile.model_validate(
            {
                "method_version": "test",
                "price_reference_period": "2026-01",
                "elementary_formula": "jevons",
                "multilateral_method": "geks_tornqvist",
                "window": {"length_periods": 3, "frequency": "M"},
                "splice_method": "mean",
                "quality_adjustment": {"enabled": True, "columns": ["stops"]},
                "booking_profile": {"source": "test", "weights": {"AP00_03": 1.0}},
                "imputation_rule": "targeted_mean",
                "outlier_rules": [],
            }
        )
        result = run_index(window_indices, published, coverage, config, "snap", "cfg")
        value = result.index_values.iloc[0]["value"]
        assert value * config.index_reference_value == 100.0
        assert run_hash("snap", "cfg") == result.run_hash


class TestUnitScalingInvariance:
    """A currency rescaling (paise<->rupees, INR<->USD) must never move an index."""

    @given(
        prices=st.lists(
            st.floats(min_value=1.0, max_value=1e5, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=6,
            unique=True,
        ),
        scale=st.floats(min_value=1e-2, max_value=1e2, allow_nan=False, allow_infinity=False),
    )
    def test_geks_tornqvist_is_scale_invariant(self, prices: list[float], scale: float) -> None:
        n = len(prices)
        rows = []
        rng = np.random.default_rng(abs(hash(tuple(prices))) % (2**32))
        for t in range(3):
            multiplier = 1.0 + 0.1 * t
            for i, base_price in enumerate(prices):
                rows.append((t, f"P{i}", base_price * multiplier, float(rng.uniform(0.1, 1.0))))
        panel = pd.DataFrame(rows, columns=["period", "product_id", "price", "share"])

        baseline = geks_tornqvist(panel, window_days=93)
        rescaled_panel = panel.assign(price=panel["price"] * scale)
        rescaled = geks_tornqvist(rescaled_panel, window_days=93)

        pd.testing.assert_series_equal(baseline, rescaled, check_exact=False, rtol=1e-8)
        assert n >= 2  # sanity: hypothesis actually varied the product count
