"""Elementary aggregates: Jevons, Dutot, Carli.

Worked example (used across all three formulas below):

    p_0 = [100, 200,  50]
    p_t = [110, 180,  60]
    relatives = p_t / p_0 = [1.1, 0.9, 1.2]

    dutot = mean(p_t) / mean(p_0) = (110+180+60)/3 / (100+200+50)/3 = 350/350 = 1.0
    carli = mean(relatives) = (1.1 + 0.9 + 1.2) / 3 = 3.2/3 = 16/15 = 1.0666666667
    jevons = (1.1 * 0.9 * 1.2) ** (1/3) = 1.188 ** (1/3) = 1.0591045006

A second, two-product example:

    p_0 = [1000, 4000], p_t = [1200, 3600], relatives = [1.2, 0.9]
    dutot = (1200+3600)/2 / (1000+4000)/2 = 2400/2500 = 0.96
    carli = (1.2 + 0.9)/2 = 1.05
    jevons = (1.2 * 0.9) ** 0.5 = 1.08 ** 0.5 = 1.0392304845
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from apix_core.config.method import ElementaryFormula
from apix_core.index.elementary import DEFAULT_FORMULA, carli, dutot, elementary_index, jevons

P0_A = [100.0, 200.0, 50.0]
PT_A = [110.0, 180.0, 60.0]
P0_B = [1000.0, 4000.0]
PT_B = [1200.0, 3600.0]


class TestJevonsGolden:
    def test_three_products(self) -> None:
        assert jevons(PT_A, P0_A) == pytest.approx(1.0591045006, abs=1e-10)

    def test_two_products(self) -> None:
        assert jevons(PT_B, P0_B) == pytest.approx(1.0392304845, abs=1e-10)

    def test_is_the_published_default(self) -> None:
        assert DEFAULT_FORMULA is ElementaryFormula.JEVONS


class TestDutotGolden:
    def test_three_products_equal_totals_gives_exactly_one(self) -> None:
        # (110+180+60) == (100+200+50) == 350: the arithmetic-mean ratio is exact.
        assert dutot(PT_A, P0_A) == pytest.approx(1.0, abs=1e-10)

    def test_two_products(self) -> None:
        assert dutot(PT_B, P0_B) == pytest.approx(0.96, abs=1e-10)


class TestCarliGolden:
    def test_three_products(self) -> None:
        assert carli(PT_A, P0_A) == pytest.approx(16.0 / 15.0, abs=1e-10)

    def test_two_products(self) -> None:
        assert carli(PT_B, P0_B) == pytest.approx(1.05, abs=1e-10)


class TestDispatch:
    def test_elementary_index_dispatches_to_jevons(self) -> None:
        assert elementary_index(PT_A, P0_A, ElementaryFormula.JEVONS) == jevons(PT_A, P0_A)

    def test_elementary_index_dispatches_to_dutot(self) -> None:
        assert elementary_index(PT_A, P0_A, ElementaryFormula.DUTOT) == dutot(PT_A, P0_A)

    def test_elementary_index_dispatches_to_carli(self) -> None:
        assert elementary_index(PT_A, P0_A, ElementaryFormula.CARLI) == carli(PT_A, P0_A)


class TestValidation:
    def test_mismatched_shapes_rejected(self) -> None:
        with pytest.raises(ValueError, match="matched"):
            jevons([1.0, 2.0], [1.0])

    def test_empty_input_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            jevons([], [])

    def test_non_positive_price_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            jevons([0.0], [10.0])

    def test_negative_price_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            carli([-5.0], [10.0])

    def test_non_one_dimensional_input_rejected(self) -> None:
        with pytest.raises(ValueError, match="one-dimensional"):
            jevons([[1.0, 2.0], [3.0, 4.0]], [[1.0, 2.0], [3.0, 4.0]])


class TestProperties:
    """Invariants that must hold for *any* matched price pair, not just the examples."""

    def test_identical_prices_give_exactly_one_for_every_formula(self) -> None:
        prices = [100.0, 250.5, 3.0]
        assert jevons(prices, prices) == 1.0
        assert dutot(prices, prices) == 1.0
        assert carli(prices, prices) == 1.0

    def test_jevons_time_reversal(self) -> None:
        """jevons(p_t, p_0) * jevons(p_0, p_t) == 1 exactly — Carli cannot do this."""
        forward = jevons(PT_A, P0_A)
        backward = jevons(P0_A, PT_A)
        assert forward * backward == pytest.approx(1.0, abs=1e-12)

    def test_carli_fails_time_reversal_on_bouncing_prices(self) -> None:
        """The textbook demonstration of why Carli is rejected as a published formula."""
        forward = carli(PT_A, P0_A)
        backward = carli(P0_A, PT_A)
        assert forward * backward != pytest.approx(1.0, abs=1e-6)
        assert forward * backward > 1.0  # Carli's bias is always upward

    @given(
        prices=st.lists(
            st.floats(min_value=1.0, max_value=1e6, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=20,
        ),
        scale=st.floats(min_value=1e-3, max_value=1e3, allow_nan=False, allow_infinity=False),
    )
    def test_jevons_is_invariant_to_a_common_unit_rescaling(
        self, prices: list[float], scale: float
    ) -> None:
        """Rescaling every price in both periods by the same factor (e.g. paise to
        rupees, or INR to USD) must not move the index — only *relative* price
        movement should.
        """
        p0 = np.array(prices)
        pt = p0 * 1.37  # an arbitrary but fixed relative movement
        baseline = jevons(pt, p0)
        rescaled = jevons(pt * scale, p0 * scale)
        assert rescaled == pytest.approx(baseline, rel=1e-9)

    @given(
        prices=st.lists(
            st.floats(min_value=1.0, max_value=1e6, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=20,
        )
    )
    def test_dutot_and_carli_are_also_scale_invariant(self, prices: list[float]) -> None:
        p0 = np.array(prices)
        pt = p0 * 1.37
        for formula in (dutot, carli):
            baseline = formula(pt, p0)
            rescaled = formula(pt * 100.0, p0 * 100.0)
            assert rescaled == pytest.approx(baseline, rel=1e-9)
