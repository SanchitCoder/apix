"""Back-test scoring: the honest-empty-result case matters as much as the real one —
there is no real DGCA average-fare data loaded in this repository yet (see
docs/data-sources.md), so the zero-coverage path is the one `make backtest` actually
exercises today.
"""

from __future__ import annotations

import pandas as pd
import pytest

from apix_core.backtest.score import score_apix_vs_dgca, score_national_and_per_route


def _series(values: list[float], periods: list[str]) -> pd.Series:
    return pd.Series(values, index=pd.PeriodIndex(periods, freq="M"))


class TestScoreApixVsDgca:
    def test_no_overlap_gives_an_honest_zero_coverage_result(self) -> None:
        apix = _series([100.0, 101.0], ["2026-01", "2026-02"])
        reference = _series([200.0, 201.0], ["2026-06", "2026-07"])
        score = score_apix_vs_dgca(apix, reference, min_periods=2)
        assert score.n_periods == 0
        assert score.correlation is None
        assert score.mape is None
        assert "no overlapping periods" in score.coverage_note

    def test_below_min_periods_reports_the_count_but_no_metrics(self) -> None:
        apix = _series([100.0, 101.0, 102.0], ["2026-01", "2026-02", "2026-03"])
        reference = _series([200.0, 201.0], ["2026-01", "2026-02"])
        score = score_apix_vs_dgca(apix, reference, min_periods=5)
        assert score.n_periods == 2
        assert score.correlation is None
        assert "min_periods requires 5" in score.coverage_note

    def test_perfectly_correlated_series_scores_correlation_one(self) -> None:
        periods = [f"2026-{m:02d}" for m in range(1, 13)]
        apix = _series([100.0 + i for i in range(12)], periods)
        reference = _series([50.0 + 2 * i for i in range(12)], periods)
        score = score_apix_vs_dgca(apix, reference, min_periods=5)
        assert score.n_periods == 12
        assert score.correlation == pytest.approx(1.0, abs=1e-9)
        assert score.directional_accuracy == pytest.approx(100.0)

    def test_mape_is_computed_correctly(self) -> None:
        periods = [f"2026-{m:02d}" for m in range(1, 6)]
        apix = _series([110.0, 110.0, 110.0, 110.0, 110.0], periods)
        reference = _series([100.0, 100.0, 100.0, 100.0, 100.0], periods)
        score = score_apix_vs_dgca(apix, reference, min_periods=2)
        assert score.mape == pytest.approx(10.0)

    def test_directional_accuracy_penalises_wrong_direction_moves(self) -> None:
        periods = [f"2026-{m:02d}" for m in range(1, 6)]
        apix = _series([100.0, 101.0, 99.0, 105.0, 104.0], periods)
        reference = _series([100.0, 101.0, 102.0, 103.0, 104.0], periods)
        score = score_apix_vs_dgca(apix, reference, min_periods=2)
        # apix moves: up, down, up, down; reference moves: up, up, up, up
        # matches on moves 1 and 3 -> 50%
        assert score.directional_accuracy == pytest.approx(50.0)

    def test_min_periods_below_two_is_a_value_error(self) -> None:
        apix = _series([100.0], ["2026-01"])
        with pytest.raises(ValueError, match="min_periods must be at least 2"):
            score_apix_vs_dgca(apix, apix, min_periods=1)


class TestScoreNationalAndPerRoute:
    def test_national_score_is_independent_of_per_route_coverage(self) -> None:
        periods = [f"2026-{m:02d}" for m in range(1, 6)]
        national_apix = _series([100.0, 101.0, 102.0, 103.0, 104.0], periods)
        national_ref = _series([90.0, 91.0, 92.0, 93.0, 94.0], periods)
        scores = score_national_and_per_route(
            national_apix, national_ref, apix_by_route={}, reference_by_route={}, min_periods=2
        )
        assert len(scores) == 1
        assert scores[0].scope == "national"
        assert scores[0].n_periods == 5

    def test_only_routes_present_in_both_are_scored(self) -> None:
        periods = [f"2026-{m:02d}" for m in range(1, 6)]
        national = _series([100.0] * 5, periods)
        by_route_apix = {
            "DEL-BOM": _series([100.0] * 5, periods),
            "BOM-DEL": _series([100.0] * 5, periods),
        }
        by_route_ref = {"DEL-BOM": _series([90.0] * 5, periods)}
        scores = score_national_and_per_route(
            national, national, by_route_apix, by_route_ref, min_periods=2
        )
        scopes = [s.scope for s in scores]
        assert scopes == ["national", "DEL-BOM"]
