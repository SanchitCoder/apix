"""Splicing methods.

Shared worked example for the golden tests below:

    window_index (periods 0..4) = [1.00, 1.20, 1.50, 1.35, 1.62]
    published (periods 0..3)    = {0: 100.0, 1: 115.0, 2: 140.0, 3: 130.0}

    movement (k=1): anchor = published[3] = 130.0, ratio = 1.62/1.35 = 1.2
                    -> 130.0 * 1.2 = 156.0
    window   (k=4): anchor = published[0] = 100.0, ratio = 1.62/1.00 = 1.62
                    -> 100.0 * 1.62 = 162.0
    half     (k=2): anchor = published[2] = 140.0, ratio = 1.62/1.50 = 1.08
                    -> 140.0 * 1.08 = 151.2
    mean: geometric mean of the four per-k estimates
      k=1 -> 156.0, k=2 -> 151.2, k=3 -> anchor=published[1]=115.0, ratio=1.62/1.20=1.35
                                          -> 115.0*1.35 = 155.25
      k=4 -> 162.0
      mean = (156.0 * 151.2 * 155.25 * 162.0) ** 0.25 = 156.0650849970
"""

from __future__ import annotations

import pandas as pd
import pytest

from apix_core.config.method import SpliceMethod
from apix_core.index.splice import (
    DEFAULT_METHOD,
    fbew_splice,
    fbmw_splice,
    half_splice,
    mean_splice,
    movement_splice,
    should_rebase,
    splice,
    splice_link_estimate,
    window_splice,
)

WINDOW_INDEX = pd.Series([1.00, 1.20, 1.50, 1.35, 1.62], index=[0, 1, 2, 3, 4])
PUBLISHED = pd.Series({0: 100.0, 1: 115.0, 2: 140.0, 3: 130.0})


class TestGolden:
    def test_movement_splice(self) -> None:
        assert movement_splice(PUBLISHED, WINDOW_INDEX) == pytest.approx(156.0, abs=1e-9)

    def test_window_splice(self) -> None:
        assert window_splice(PUBLISHED, WINDOW_INDEX) == pytest.approx(162.0, abs=1e-9)

    def test_half_splice(self) -> None:
        assert half_splice(PUBLISHED, WINDOW_INDEX) == pytest.approx(151.2, abs=1e-9)

    def test_mean_splice(self) -> None:
        assert mean_splice(PUBLISHED, WINDOW_INDEX) == pytest.approx(156.0650849970, abs=1e-8)

    def test_fbew_is_window_splice_over_an_expanding_window(self) -> None:
        assert fbew_splice(PUBLISHED, WINDOW_INDEX) == window_splice(PUBLISHED, WINDOW_INDEX)

    def test_fbmw_is_window_splice_between_scheduled_rebases(self) -> None:
        assert fbmw_splice(PUBLISHED, WINDOW_INDEX) == window_splice(PUBLISHED, WINDOW_INDEX)

    def test_splice_link_estimate_at_k1_is_movement(self) -> None:
        assert splice_link_estimate(PUBLISHED, WINDOW_INDEX, 1) == movement_splice(
            PUBLISHED, WINDOW_INDEX
        )

    def test_splice_link_estimate_at_full_window_is_window_splice(self) -> None:
        k = len(WINDOW_INDEX) - 1
        assert splice_link_estimate(PUBLISHED, WINDOW_INDEX, k) == window_splice(
            PUBLISHED, WINDOW_INDEX
        )


class TestDispatch:
    @pytest.mark.parametrize(
        ("method", "expected_fn"),
        [
            (SpliceMethod.MOVEMENT, movement_splice),
            (SpliceMethod.WINDOW, window_splice),
            (SpliceMethod.HALF, half_splice),
            (SpliceMethod.MEAN, mean_splice),
            (SpliceMethod.FBEW, fbew_splice),
            (SpliceMethod.FBMW, fbmw_splice),
        ],
    )
    def test_dispatch_matches_direct_call(self, method: SpliceMethod, expected_fn: object) -> None:
        assert splice(method, PUBLISHED, WINDOW_INDEX) == expected_fn(PUBLISHED, WINDOW_INDEX)  # type: ignore[operator]

    def test_default_is_mean(self) -> None:
        assert DEFAULT_METHOD is SpliceMethod.MEAN


class TestNonRevision:
    """The property that makes splicing publishable at all: history never moves."""

    def test_no_splice_method_can_change_a_published_period(self) -> None:
        before = PUBLISHED.copy()
        for method in SpliceMethod:
            splice(method, PUBLISHED, WINDOW_INDEX)
            pd.testing.assert_series_equal(PUBLISHED, before)

    def test_extending_the_series_only_ever_adds_the_newest_period(self) -> None:
        new_value = splice(SpliceMethod.MOVEMENT, PUBLISHED, WINDOW_INDEX)
        extended = pd.concat([PUBLISHED, pd.Series({4: new_value})])
        # Every period that was published before stays byte-identical.
        pd.testing.assert_series_equal(extended.loc[PUBLISHED.index], PUBLISHED)


class TestShouldRebase:
    def test_not_due_before_the_interval(self) -> None:
        assert should_rebase(periods_since_last_rebase=5, rebase_every=12) is False

    def test_due_at_the_interval(self) -> None:
        assert should_rebase(periods_since_last_rebase=12, rebase_every=12) is True

    def test_due_past_the_interval(self) -> None:
        assert should_rebase(periods_since_last_rebase=13, rebase_every=12) is True

    def test_rejects_non_positive_interval(self) -> None:
        with pytest.raises(ValueError, match="rebase_every"):
            should_rebase(periods_since_last_rebase=0, rebase_every=0)

    def test_rejects_negative_periods_since_last_rebase(self) -> None:
        with pytest.raises(ValueError, match="periods_since_last_rebase"):
            should_rebase(periods_since_last_rebase=-1, rebase_every=12)


class TestValidation:
    def test_requires_at_least_two_periods_in_the_window(self) -> None:
        with pytest.raises(ValueError, match="at least two periods"):
            movement_splice(PUBLISHED, pd.Series([1.0], index=[0]))

    def test_rejects_non_positive_window_levels(self) -> None:
        bad = pd.Series([1.0, -1.0], index=[0, 1])
        with pytest.raises(ValueError, match="positive"):
            movement_splice(PUBLISHED, bad)

    def test_rejects_a_window_the_published_series_cannot_cover(self) -> None:
        sparse_published = pd.Series({0: 100.0})  # missing periods 1, 2
        with pytest.raises(ValueError, match="missing required periods"):
            window_splice(sparse_published, WINDOW_INDEX)

    def test_rejects_a_non_positive_published_level(self) -> None:
        bad_published = pd.Series({0: 100.0, 1: 115.0, 2: -1.0, 3: 130.0})
        with pytest.raises(ValueError, match="published index levels must be strictly positive"):
            window_splice(bad_published, WINDOW_INDEX)

    def test_splice_link_estimate_rejects_out_of_range_k(self) -> None:
        with pytest.raises(ValueError, match="k must be between"):
            splice_link_estimate(PUBLISHED, WINDOW_INDEX, 0)
        with pytest.raises(ValueError, match="k must be between"):
            splice_link_estimate(PUBLISHED, WINDOW_INDEX, len(WINDOW_INDEX))
