"""``make index-run`` — the synthetic-dataset demonstration harness.

Not a unit test of index maths (that's ``tests/apix_core/index/``): this exercises the
whole pipeline end to end — synthetic generation, GEKS-Törnqvist per cell, the
aggregation hierarchy — against the real shipped config.
"""

from __future__ import annotations

from datetime import date

import pytest

from apix_scheduler.index_run import IndexRunReport, run

AS_OF = date(2026, 9, 1)
DAYS = 14


@pytest.fixture(scope="module")
def report() -> IndexRunReport:
    """One run, shared by every test below — each call regenerates the synthetic
    dataset and re-estimates GEKS-Törnqvist for ~1,400 cells, so this is deliberately
    not a per-test fixture.
    """
    return run(as_of=AS_OF, days=DAYS)


class TestRun:
    def test_produces_a_route_index_over_the_synthetic_dataset(
        self, report: IndexRunReport
    ) -> None:
        assert not report.routes.empty
        assert {"route_code", "index_value", "n_quotes", "coverage_pct"} <= set(
            report.routes.columns
        )
        assert (report.routes["index_value"] > 0).all()
        assert (report.routes["n_quotes"] > 0).all()

    def test_reports_sub_indices(self, report: IndexRunReport) -> None:
        assert not report.by_carrier_type.empty
        assert not report.by_advance_window.empty

    def test_national_index_computes_now_that_the_basket_has_real_dgca_weights(
        self, report: IndexRunReport
    ) -> None:
        """config/basket.yaml's dgca_pax_share is now populated from a real DGCA
        monthly release (db/seeds/dgca/2026-07.csv — see docs/data-sources.md), so the
        national aggregate can weight routes and publish — no fabricated weight is
        involved, only real, loaded ones (CLAUDE.md principle 5).
        """
        assert report.national_error is None
        assert report.national is not None
        assert not report.national.empty
        assert (report.national["index_value"] > 0).all()

    def test_skipped_cells_carry_a_reason(self, report: IndexRunReport) -> None:
        for skip in report.skipped_cells:
            assert skip.reason
            assert skip.route_code
            assert skip.advance_window


@pytest.mark.slow
class TestReproducibility:
    def test_is_deterministic_for_the_same_inputs(self) -> None:
        """The synthetic generator is seeded and the index maths are pure, so the
        same (as_of, days) must reproduce the same route index exactly. Runs the
        pipeline a second time deliberately, so it is marked slow.
        """
        first = run(as_of=AS_OF, days=DAYS)
        second = run(as_of=AS_OF, days=DAYS)

        assert first.routes.equals(second.routes)
