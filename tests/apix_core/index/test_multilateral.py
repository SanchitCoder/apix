"""GEKS-Törnqvist and Time Product Dummy.

This file's headline is ``test_chain_drift_*``: the proof, not just an assertion, that
a multilateral method is doing its job. See ``docs/adr/0002-why-multilateral-index.md``
for why this matters for airfares specifically.
"""

from __future__ import annotations

from itertools import pairwise
from typing import ClassVar

import numpy as np
import pandas as pd
import pytest

from apix_core.index.elementary import jevons
from apix_core.index.multilateral import geks_tornqvist, time_product_dummy, tornqvist_bilateral


def _panel(rows: list[tuple[int, str, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["period", "product_id", "price", "share"])


class TestTornqvistBilateralGolden:
    """Two products, two periods.

    p_0 = [100, 200], p_1 = [120, 180], s_0 = [0.4, 0.6], s_1 = [0.5, 0.5]
    avg share = [0.45, 0.55] (sums to 1, no renormalisation needed)
    ln(p_1/p_0) = [ln(1.2), ln(0.9)] = [0.1823215568, -0.1053605157]
    ln P_T = 0.45*0.1823215568 + 0.55*(-0.1053605157) = 0.0820947006 - 0.0579482836
           = 0.0241464170
    P_T = exp(0.0241464170) = 1.0244... -> 1.0243890816
    """

    def test_two_product_bilateral(self) -> None:
        p0 = pd.Series({"A": 100.0, "B": 200.0})
        p1 = pd.Series({"A": 120.0, "B": 180.0})
        s0 = pd.Series({"A": 0.4, "B": 0.6})
        s1 = pd.Series({"A": 0.5, "B": 0.5})
        assert tornqvist_bilateral(p0, p1, s0, s1) == pytest.approx(1.0243890816, abs=1e-10)

    def test_time_reversal_is_exact(self) -> None:
        p0 = pd.Series({"A": 100.0, "B": 200.0, "C": 50.0})
        p1 = pd.Series({"A": 120.0, "B": 180.0, "C": 55.0})
        s0 = pd.Series({"A": 0.4, "B": 0.5, "C": 0.1})
        s1 = pd.Series({"A": 0.3, "B": 0.6, "C": 0.1})
        forward = tornqvist_bilateral(p0, p1, s0, s1)
        backward = tornqvist_bilateral(p1, p0, s1, s0)
        assert forward * backward == pytest.approx(1.0, abs=1e-12)

    def test_only_common_products_are_used(self) -> None:
        p0 = pd.Series({"A": 100.0, "B": 200.0})
        p1 = pd.Series({"A": 120.0, "C": 999.0})  # B absent, C new — neither matched
        s0 = pd.Series({"A": 0.4, "B": 0.6})
        s1 = pd.Series({"A": 1.0, "C": 1.0})
        # Only A is common; the index collapses to A's own relative.
        assert tornqvist_bilateral(p0, p1, s0, s1) == pytest.approx(1.2, abs=1e-10)


class TestGeksTornqvistGolden:
    def test_two_periods_equals_the_plain_bilateral_index(self) -> None:
        """With exactly two periods, GEKS has nothing to reconcile: it must reduce to
        the bilateral Törnqvist index between them, exactly.
        """
        panel = _panel(
            [
                (0, "A", 100.0, 0.4),
                (0, "B", 200.0, 0.6),
                (1, "A", 120.0, 0.5),
                (1, "B", 180.0, 0.5),
            ]
        )
        result = geks_tornqvist(panel, window_days=31)
        expected = tornqvist_bilateral(
            pd.Series({"A": 100.0, "B": 200.0}),
            pd.Series({"A": 120.0, "B": 180.0}),
            pd.Series({"A": 0.4, "B": 0.6}),
            pd.Series({"A": 0.5, "B": 0.5}),
        )
        assert result.loc[0] == pytest.approx(1.0, abs=1e-12)
        assert result.loc[1] == pytest.approx(expected, abs=1e-10)

    def test_balanced_round_trip_returns_to_exactly_one(self) -> None:
        """A fixed (balanced) product set that returns to its period-0 prices must
        give a GEKS level of exactly 1.0 at the final period, regardless of what the
        prices did along the way.
        """
        panel = _panel(
            [
                (0, "A", 100.0, 0.5),
                (0, "B", 200.0, 0.5),
                (1, "A", 110.0, 0.5),
                (1, "B", 190.0, 0.5),
                (2, "A", 100.0, 0.5),
                (2, "B", 200.0, 0.5),
            ]
        )
        result = geks_tornqvist(panel, window_days=62)
        assert result.loc[2] == pytest.approx(1.0, abs=1e-10)


class TestChainDrift:
    """The headline test: GEKS-Törnqvist is transitive under product churn; a naive
    daily-chained Jevons index is not.

    Construction (this is exactly the failure mode
    ``docs/adr/0002-why-multilateral-index.md`` describes: "the product set churns
    violently... the error compounds"):

    * Product A is present in every period at a constant price of 100 — the
      "continuously-available itinerary".
    * Product B is present at periods 0 and 3 only, at a constant price of 100 — an
      itinerary that goes temporarily unavailable (schedule change, fare brand
      retired) and comes back at the same price.
    * Product C fills the gap while B is away (periods 1, 2), standing in as "the
      itinerary that happened to be bookable that week" — priced 60 at period 1, then
      90 at period 2 (a genuine +50% move *while B is unobservable*).

    By period 3, the only two products that were ever actually compared end to end (A
    and B) are back to their period-0 prices exactly. A price index computed directly
    on {A, B} between periods 0 and 3 must therefore read 1.0. That is what
    GEKS-Törnqvist reports.

    A naive bilateral chain instead links period to period using whichever products
    are matched *at that link*:

        link(0->1): matched = {A}            -> ratio = 100/100        = 1.0
        link(1->2): matched = {A, C}         -> ratio = geomean(1, 90/60) = sqrt(1.5)
        link(2->3): matched = {A}            -> ratio = 100/100        = 1.0

    C's mid-window price jump gets baked into the chain (via link 1->2) even though C
    never coexists with B and never enters the direct 0-vs-3 comparison. The chained
    product is exactly ``sqrt(1.5) = 1.2247448714`` — a fabricated 22.5% "increase"
    with no basis in what A or B actually did.
    """

    ROWS: ClassVar[list[tuple[int, str, float, float]]] = [
        (0, "A", 100.0, 0.5),
        (0, "B", 100.0, 0.5),
        (1, "A", 100.0, 0.6),
        (1, "C", 60.0, 0.4),
        (2, "A", 100.0, 0.6),
        (2, "C", 90.0, 0.4),
        (3, "A", 100.0, 0.5),
        (3, "B", 100.0, 0.5),
    ]

    def _naive_daily_chained_jevons(self, panel: pd.DataFrame) -> pd.Series:
        periods = sorted(panel["period"].unique())
        levels = {periods[0]: 1.0}
        chain = 1.0
        for prev, cur in pairwise(periods):
            prev_block = panel.loc[panel["period"] == prev].set_index("product_id")["price"]
            cur_block = panel.loc[panel["period"] == cur].set_index("product_id")["price"]
            common = prev_block.index.intersection(cur_block.index)
            chain *= jevons(cur_block.loc[common], prev_block.loc[common])
            levels[cur] = chain
        return pd.Series(levels).reindex(periods)

    def test_chain_drift_geks_tornqvist_returns_but_naive_chained_jevons_does_not(self) -> None:
        panel = _panel(self.ROWS)

        geks = geks_tornqvist(panel, window_days=93)
        naive_chain = self._naive_daily_chained_jevons(panel)

        # The multilateral method: the window's own transitive comparison correctly
        # reports that nothing changed between the only two periods A and B actually
        # bridge.
        assert geks.loc[3] == pytest.approx(1.0, abs=1e-10)

        # The naive chain: drifted by exactly sqrt(1.5), purely from routing the
        # comparison through a temporarily-substituted product.
        assert naive_chain.loc[3] == pytest.approx(np.sqrt(1.5), abs=1e-10)
        assert naive_chain.loc[3] != pytest.approx(1.0, abs=1e-6)

        # The gap between the two methods at the final period is the chain-drift
        # error this whole module exists to eliminate.
        drift = abs(naive_chain.loc[3] - geks.loc[3])
        assert drift == pytest.approx(np.sqrt(1.5) - 1.0, abs=1e-10)
        assert drift > 0.2  # not a rounding artefact — a real, material divergence

    def test_time_product_dummy_is_also_immune_to_the_same_churn(self) -> None:
        """TPD folds every observation into one regression rather than chaining
        pairwise, so it is exposed to the same churn and must also resist it.
        """
        panel = _panel(self.ROWS)
        tpd = time_product_dummy(panel, window_days=93)
        assert tpd.loc[3] == pytest.approx(1.0, abs=1e-8)


class TestTimeProductDummyGolden:
    def test_two_periods_unweighted_equals_jevons(self) -> None:
        """Diewert (2004): the bilateral, unweighted time-dummy hedonic regression is
        the country-product-dummy method, which reduces exactly to the unweighted
        Jevons index across the matched products.

        p_0 = [100, 200], p_1 = [120, 170] (equal weights)
        jevons = sqrt(1.2 * 0.85) = sqrt(1.02) = 1.0099504938
        """
        panel = _panel(
            [
                (0, "A", 100.0, 1.0),
                (0, "B", 200.0, 1.0),
                (1, "A", 120.0, 1.0),
                (1, "B", 170.0, 1.0),
            ]
        )
        tpd = time_product_dummy(panel, window_days=31)
        expected = jevons([120.0, 170.0], [100.0, 200.0])
        assert tpd.loc[0] == pytest.approx(1.0, abs=1e-10)
        assert tpd.loc[1] == pytest.approx(expected, abs=1e-8)
        assert tpd.loc[1] == pytest.approx(1.0099504938, abs=1e-8)

    def test_all_zero_shares_fall_back_to_an_unweighted_regression(self) -> None:
        """No shares/weights available at all (every observation's share is 0) is a
        degenerate but real case — apix_core.testing has no quantity data to derive a
        share from for a brand-new stratum. TPD should not divide by zero; it falls
        back to equal weights and reduces to the unweighted-Jevons special case.
        """
        panel = _panel(
            [
                (0, "A", 100.0, 0.0),
                (0, "B", 200.0, 0.0),
                (1, "A", 120.0, 0.0),
                (1, "B", 170.0, 0.0),
            ]
        )
        tpd = time_product_dummy(panel, window_days=31)
        expected = jevons([120.0, 170.0], [100.0, 200.0])
        assert tpd.loc[1] == pytest.approx(expected, abs=1e-8)

    def test_base_period_is_always_exactly_one(self) -> None:
        panel = _panel(
            [
                (0, "A", 100.0, 1.0),
                (0, "B", 50.0, 1.0),
                (1, "A", 150.0, 1.0),
                (1, "B", 40.0, 1.0),
                (2, "A", 90.0, 1.0),
                (2, "B", 200.0, 1.0),
            ]
        )
        tpd = time_product_dummy(panel, window_days=62)
        assert tpd.loc[0] == 1.0


class TestValidation:
    def test_geks_requires_at_least_two_periods(self) -> None:
        panel = _panel([(0, "A", 100.0, 1.0)])
        with pytest.raises(ValueError, match="at least two periods"):
            geks_tornqvist(panel, window_days=31)

    def test_geks_rejects_non_positive_prices(self) -> None:
        panel = _panel([(0, "A", 0.0, 1.0), (1, "A", 100.0, 1.0)])
        with pytest.raises(ValueError, match="positive"):
            geks_tornqvist(panel, window_days=31)

    def test_geks_rejects_a_window_wider_than_declared(self) -> None:
        panel = _panel([(0, "A", 100.0, 1.0), (400, "A", 110.0, 1.0)])
        with pytest.raises(ValueError, match="window_days"):
            geks_tornqvist(panel, window_days=31)

    def test_tpd_rejects_rank_deficient_panel(self) -> None:
        """A single product observed in only one of two periods can't separate a time
        effect from a product effect.
        """
        panel = _panel([(0, "A", 100.0, 1.0), (1, "B", 110.0, 1.0)])
        with pytest.raises(ValueError, match="rank-deficient"):
            time_product_dummy(panel, window_days=31)

    def test_missing_columns_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="missing required columns"):
            geks_tornqvist(pd.DataFrame({"period": [0, 1]}), window_days=31)

    def test_empty_panel_is_rejected(self) -> None:
        empty = pd.DataFrame(columns=["period", "product_id", "price", "share"])
        with pytest.raises(ValueError, match="at least one observation"):
            geks_tornqvist(empty, window_days=31)

    def test_negative_share_is_rejected(self) -> None:
        panel = _panel([(0, "A", 100.0, -0.1), (1, "A", 110.0, 1.0)])
        with pytest.raises(ValueError, match="non-negative"):
            geks_tornqvist(panel, window_days=31)

    def test_geks_reports_which_periods_share_no_product(self) -> None:
        """Three periods, but periods 0 and 2 share no product at all (only 1 bridges
        0->1 and 1->2). The error must name the offending pair, not just "somewhere".
        """
        panel = _panel(
            [
                (0, "A", 100.0, 1.0),
                (0, "B", 100.0, 1.0),
                (1, "B", 110.0, 1.0),
                (1, "C", 90.0, 1.0),
                (2, "C", 95.0, 1.0),
            ]
        )
        with pytest.raises(ValueError, match=r"no products are common.*0.*and.*2"):
            geks_tornqvist(panel, window_days=62)

    def test_geks_rejects_window_days_below_one(self) -> None:
        panel = _panel([(0, "A", 100.0, 1.0), (1, "A", 110.0, 1.0)])
        with pytest.raises(ValueError, match="window_days must be >= 1"):
            geks_tornqvist(panel, window_days=0)

    def test_tornqvist_bilateral_rejects_disjoint_product_sets(self) -> None:
        p0 = pd.Series({"A": 100.0})
        p1 = pd.Series({"B": 110.0})
        s0 = pd.Series({"A": 1.0})
        s1 = pd.Series({"B": 1.0})
        with pytest.raises(ValueError, match="no products are common"):
            tornqvist_bilateral(p0, p1, s0, s1)

    def test_tornqvist_bilateral_rejects_non_positive_matched_price(self) -> None:
        p0 = pd.Series({"A": 100.0})
        p1 = pd.Series({"A": 0.0})
        s0 = pd.Series({"A": 1.0})
        s1 = pd.Series({"A": 1.0})
        with pytest.raises(ValueError, match="positive"):
            tornqvist_bilateral(p0, p1, s0, s1)

    def test_tornqvist_bilateral_rejects_zero_matched_shares(self) -> None:
        p0 = pd.Series({"A": 100.0})
        p1 = pd.Series({"A": 110.0})
        s0 = pd.Series({"A": 0.0})
        s1 = pd.Series({"A": 0.0})
        with pytest.raises(ValueError, match="matched shares sum to zero"):
            tornqvist_bilateral(p0, p1, s0, s1)
