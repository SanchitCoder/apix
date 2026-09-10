"""Movement decomposition: the required test — components sum to the total change,
to within floating-point tolerance — on a hand fixture and under randomised weights.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apix_core.nowcast.decomposition import bennet_two_factor, decompose_movement


def _elementary(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _two_route_two_window_two_carrier_fixture(total: bool) -> pd.DataFrame:
    """Total-fare and base-fare elementary cells for the same tiny basket: two
    routes, two advance windows, two carriers each. Hand-constructed so the
    total-vs-base gap is entirely attributable to a uniform 20% tax/fee loading —
    the tax_fee_effect this fixture should recover.
    """
    base_values = {
        ("DEL-BOM", "AP00_03", "6E"): (100.0, 108.0, 40, 44),
        ("DEL-BOM", "AP00_03", "AI"): (102.0, 103.0, 20, 24),
        ("DEL-BOM", "AP04_07", "6E"): (95.0, 99.0, 30, 33),
        ("DEL-BOM", "AP04_07", "AI"): (97.0, 96.0, 15, 18),
        ("BOM-DEL", "AP00_03", "6E"): (110.0, 115.0, 25, 28),
        ("BOM-DEL", "AP00_03", "AI"): (108.0, 111.0, 18, 16),
        ("BOM-DEL", "AP04_07", "6E"): (104.0, 107.0, 22, 20),
        ("BOM-DEL", "AP04_07", "AI"): (103.0, 105.0, 12, 14),
    }
    tax_multiplier = 1.2 if total else 1.0
    rows = []
    for (route, window, carrier), (v_prior, v_current, n_prior, n_current) in base_values.items():
        rows.append(
            {
                "route_code": route,
                "advance_window": window,
                "carrier_iata": carrier,
                "index_value_prior": v_prior * tax_multiplier,
                "index_value_current": v_current * tax_multiplier,
                "n_quotes_prior": n_prior,
                "n_quotes_current": n_current,
            }
        )
    return _elementary(rows)


_BOOKING_PROFILE = {"AP00_03": 0.6, "AP04_07": 0.4}
_DGCA_PAX_SHARE = {"DEL-BOM": 0.55, "BOM-DEL": 0.45}


class TestBennetTwoFactor:
    def test_exact_for_a_single_weighted_sum_change(self) -> None:
        w_prior = np.array([0.5, 0.5])
        w_current = np.array([0.5, 0.5])
        x_prior = np.log(np.array([100.0, 200.0]))
        x_current = np.log(np.array([110.0, 190.0]))
        price, mix = bennet_two_factor(w_prior, w_current, x_prior, x_current)
        s_prior = np.sum(w_prior * x_prior)
        s_current = np.sum(w_current * x_current)
        assert price + mix == pytest.approx(s_current - s_prior, abs=1e-12)
        # weights unchanged -> mix effect is exactly zero
        assert mix == pytest.approx(0.0, abs=1e-12)

    @given(
        w_prior=st.lists(st.floats(0.01, 1.0), min_size=2, max_size=5),
        w_current=st.lists(st.floats(0.01, 1.0), min_size=2, max_size=5),
        x_prior=st.lists(st.floats(1.0, 1000.0), min_size=2, max_size=5),
        x_current=st.lists(st.floats(1.0, 1000.0), min_size=2, max_size=5),
    )
    @settings(max_examples=200)
    def test_exact_under_random_weights_and_values(
        self,
        w_prior: list[float],
        w_current: list[float],
        x_prior: list[float],
        x_current: list[float],
    ) -> None:
        n = min(len(w_prior), len(w_current), len(x_prior), len(x_current))
        wp = np.array(w_prior[:n]) / sum(w_prior[:n])
        wc = np.array(w_current[:n]) / sum(w_current[:n])
        xp = np.log(np.array(x_prior[:n]))
        xc = np.log(np.array(x_current[:n]))
        price, mix = bennet_two_factor(wp, wc, xp, xc)
        expected = float(np.sum(wc * xc) - np.sum(wp * xp))
        assert price + mix == pytest.approx(expected, abs=1e-9)


class TestDecomposeMovement:
    def test_components_sum_to_total_change_on_a_hand_fixture(self) -> None:
        total = _two_route_two_window_two_carrier_fixture(total=True)
        base = _two_route_two_window_two_carrier_fixture(total=False)
        result = decompose_movement(
            total, base, _BOOKING_PROFILE, _DGCA_PAX_SHARE, date(2026, 7, 1), date(2026, 8, 1)
        )
        assert result.reconstructed_total == pytest.approx(result.total_change, abs=1e-9)

    def test_static_config_weights_give_zero_window_and_route_mix(self) -> None:
        """config/method.yaml's booking_profile and config/basket.yaml's
        dgca_pax_share are period-invariant today — the honest result is that those
        two mix effects are exactly zero, not a bug (see the module docstring).
        """
        total = _two_route_two_window_two_carrier_fixture(total=True)
        base = _two_route_two_window_two_carrier_fixture(total=False)
        result = decompose_movement(
            total, base, _BOOKING_PROFILE, _DGCA_PAX_SHARE, date(2026, 7, 1), date(2026, 8, 1)
        )
        assert result.advance_window_mix_effect == pytest.approx(0.0, abs=1e-12)
        assert result.route_mix_effect == pytest.approx(0.0, abs=1e-12)

    def test_tax_fee_effect_recovers_the_uniform_tax_loading(self) -> None:
        """The fixture's total-fare basis is base-fare times a flat 1.2 multiplier in
        both periods, so the *change* in ln(total) vs ln(base) contributed by tax is
        exactly ln(1.2) - ln(1.2) = 0 — the tax rate itself didn't move, only price
        did, so tax_fee_effect should be ~0 even though tax_fee is nonzero in level.
        """
        total = _two_route_two_window_two_carrier_fixture(total=True)
        base = _two_route_two_window_two_carrier_fixture(total=False)
        result = decompose_movement(
            total, base, _BOOKING_PROFILE, _DGCA_PAX_SHARE, date(2026, 7, 1), date(2026, 8, 1)
        )
        assert result.tax_fee_effect == pytest.approx(0.0, abs=1e-9)

    def test_missing_booking_profile_weight_is_a_value_error(self) -> None:
        total = _two_route_two_window_two_carrier_fixture(total=True)
        base = _two_route_two_window_two_carrier_fixture(total=False)
        with pytest.raises(ValueError, match="booking-profile weight"):
            decompose_movement(
                total, base, {"AP00_03": 1.0}, _DGCA_PAX_SHARE, date(2026, 7, 1), date(2026, 8, 1)
            )

    def test_missing_dgca_pax_share_is_a_value_error(self) -> None:
        total = _two_route_two_window_two_carrier_fixture(total=True)
        base = _two_route_two_window_two_carrier_fixture(total=False)
        with pytest.raises(ValueError, match="dgca_pax_share weight"):
            decompose_movement(
                total,
                base,
                _BOOKING_PROFILE,
                {"DEL-BOM": 1.0},
                date(2026, 7, 1),
                date(2026, 8, 1),
            )

    @given(
        carrier_share_prior=st.floats(0.05, 0.95),
        carrier_share_current=st.floats(0.05, 0.95),
        window_weight_prior=st.floats(0.1, 0.9),
        window_weight_current=st.floats(0.1, 0.9),
        route_share_prior=st.floats(0.1, 0.9),
        route_share_current=st.floats(0.1, 0.9),
        price_move=st.floats(-0.3, 0.3),
    )
    @settings(max_examples=100)
    def test_components_sum_to_total_under_random_weights_and_moves(
        self,
        carrier_share_prior: float,
        carrier_share_current: float,
        window_weight_prior: float,
        window_weight_current: float,
        route_share_prior: float,
        route_share_current: float,
        price_move: float,
    ) -> None:
        """Randomised weights AND randomised weight *changes* (unlike the static-config
        fixtures above) — this is the property CLAUDE.md and the task require: the
        five components sum to the total change regardless of how mix shifts.
        """
        rng = np.random.default_rng(0)
        base_index = 100.0 * np.exp(rng.normal(0.0, 0.05, size=8))
        move = 100.0 * np.exp(price_move + rng.normal(0.0, 0.01, size=8))

        rows = []
        keys = [
            ("DEL-BOM", "AP00_03", "6E"),
            ("DEL-BOM", "AP00_03", "AI"),
            ("DEL-BOM", "AP04_07", "6E"),
            ("DEL-BOM", "AP04_07", "AI"),
            ("BOM-DEL", "AP00_03", "6E"),
            ("BOM-DEL", "AP00_03", "AI"),
            ("BOM-DEL", "AP04_07", "6E"),
            ("BOM-DEL", "AP04_07", "AI"),
        ]
        n_prior = [
            carrier_share_prior,
            1 - carrier_share_prior,
            carrier_share_prior,
            1 - carrier_share_prior,
        ] * 2
        n_current = [
            carrier_share_current,
            1 - carrier_share_current,
            carrier_share_current,
            1 - carrier_share_current,
        ] * 2
        for i, (route, window, carrier) in enumerate(keys):
            rows.append(
                {
                    "route_code": route,
                    "advance_window": window,
                    "carrier_iata": carrier,
                    "index_value_prior": float(base_index[i]),
                    "index_value_current": float(move[i]),
                    "n_quotes_prior": n_prior[i] * 100,
                    "n_quotes_current": n_current[i] * 100,
                }
            )
        total = _elementary(rows)
        base = _elementary(rows)  # same values -> tax_fee_effect will be exactly zero

        bp_prior = {"AP00_03": window_weight_prior, "AP04_07": 1 - window_weight_prior}
        bp_current = {"AP00_03": window_weight_current, "AP04_07": 1 - window_weight_current}
        dp_prior = {"DEL-BOM": route_share_prior, "BOM-DEL": 1 - route_share_prior}
        dp_current = {"DEL-BOM": route_share_current, "BOM-DEL": 1 - route_share_current}

        result = decompose_movement(
            total,
            base,
            bp_prior,
            dp_prior,
            date(2026, 7, 1),
            date(2026, 8, 1),
            booking_profile_weights_current=bp_current,
            dgca_pax_share_current=dp_current,
            tolerance=1e-6,
        )
        assert result.reconstructed_total == pytest.approx(result.total_change, abs=1e-6)
