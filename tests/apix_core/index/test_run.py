"""Reproducibility: the same (data_snapshot_id, method_config_hash) must produce
byte-identical output — CLAUDE.md principle 4.
"""

from __future__ import annotations

import pandas as pd
import pytest

from apix_core.config.method import MethodConfigFile, SpliceMethod
from apix_core.index.run import run_hash, run_index


def _config(splice_method: SpliceMethod = SpliceMethod.MOVEMENT) -> MethodConfigFile:
    return MethodConfigFile.model_validate(
        {
            "method_version": "test",
            "price_reference_period": "2026-01",
            "elementary_formula": "jevons",
            "multilateral_method": "geks_tornqvist",
            "window": {"length_periods": 5, "frequency": "M"},
            "splice_method": splice_method.value,
            "quality_adjustment": {"enabled": True, "columns": ["stops"]},
            "booking_profile": {"source": "test fixture", "weights": {"AP00_03": 1.0}},
            "imputation_rule": "targeted_mean",
            "outlier_rules": [],
        }
    )


class TestRunHash:
    def test_stable_for_the_same_inputs(self) -> None:
        assert run_hash("snap-1", "cfg-1") == run_hash("snap-1", "cfg-1")

    def test_changes_when_the_snapshot_changes(self) -> None:
        assert run_hash("snap-1", "cfg-1") != run_hash("snap-2", "cfg-1")

    def test_changes_when_the_config_changes(self) -> None:
        assert run_hash("snap-1", "cfg-1") != run_hash("snap-1", "cfg-2")

    def test_is_a_sha256_hex_digest(self) -> None:
        digest = run_hash("snap-1", "cfg-1")
        assert len(digest) == 64
        assert set(digest) <= set("0123456789abcdef")


class TestFirstPublication:
    """A series with no publication history yet: the window's own level is the
    publication outright.
    """

    def test_first_ever_run_of_a_series(self) -> None:
        window_indices = {"national": pd.Series([1.0, 1.05, 1.10], index=[0, 1, 2])}
        published = pd.DataFrame(columns=["series_code", "period", "value"])
        coverage = {"national": (500, 92.5)}
        config = _config()

        result = run_index(window_indices, published, coverage, config, "snap-1", "cfg-1")

        row = result.index_values.iloc[0]
        assert row["series_code"] == "national"
        assert row["period"] == 2
        assert row["value"] == pytest.approx(1.10, abs=1e-12)
        assert row["n_quotes"] == 500
        assert row["coverage_pct"] == pytest.approx(92.5)
        assert result.revisions.empty


class TestSplicedPublication:
    def test_extends_the_published_series_by_movement_splice(self) -> None:
        window_indices = {"national": pd.Series([1.0, 1.2, 1.5, 1.35, 1.62], index=[0, 1, 2, 3, 4])}
        published = pd.DataFrame(
            {
                "series_code": ["national"] * 4,
                "period": [0, 1, 2, 3],
                "value": [100.0, 115.0, 140.0, 130.0],
            }
        )
        coverage = {"national": (800, 95.0)}
        config = _config(SpliceMethod.MOVEMENT)

        result = run_index(window_indices, published, coverage, config, "snap-2", "cfg-1")

        row = result.index_values.iloc[0]
        assert row["period"] == 4
        # movement splice: 130.0 * (1.62/1.35) = 156.0 — see test_splice.py's worked example.
        assert row["value"] == pytest.approx(156.0, abs=1e-9)
        assert result.revisions.empty  # period 4 was never published before

    def test_does_not_mutate_the_published_history(self) -> None:
        window_indices = {"national": pd.Series([1.0, 1.2, 1.5, 1.35, 1.62], index=[0, 1, 2, 3, 4])}
        published = pd.DataFrame(
            {
                "series_code": ["national"] * 4,
                "period": [0, 1, 2, 3],
                "value": [100.0, 115.0, 140.0, 130.0],
            }
        )
        before = published.copy()
        coverage = {"national": (800, 95.0)}
        run_index(window_indices, published, coverage, _config(), "snap-2", "cfg-1")
        pd.testing.assert_frame_equal(published, before)


class TestReproducibility:
    """The headline property: re-running with the same inputs is byte-identical."""

    def test_same_snapshot_and_config_is_byte_identical(self) -> None:
        window_indices = {
            "national": pd.Series([1.0, 1.2, 1.5, 1.35, 1.62], index=[0, 1, 2, 3, 4]),
            "route.DEL-BOM": pd.Series([1.0, 1.1, 1.3, 1.2, 1.25], index=[0, 1, 2, 3, 4]),
        }
        published = pd.DataFrame(
            {
                "series_code": ["national", "national", "route.DEL-BOM", "route.DEL-BOM"],
                "period": [0, 1, 0, 1],
                "value": [100.0, 108.0, 100.0, 112.0],
            }
        )
        coverage = {"national": (800, 95.0), "route.DEL-BOM": (300, 88.0)}
        config = _config(SpliceMethod.MEAN)

        first = run_index(window_indices, published, coverage, config, "snap-3", "cfg-9")
        second = run_index(window_indices, published, coverage, config, "snap-3", "cfg-9")

        assert first.run_hash == second.run_hash
        pd.testing.assert_frame_equal(first.index_values, second.index_values)
        pd.testing.assert_frame_equal(first.revisions, second.revisions)

    def test_series_order_in_the_input_mapping_does_not_affect_the_result(self) -> None:
        """Dict iteration order must not leak into the published rows — that would
        make the output depend on something other than the data.
        """
        a = pd.Series([1.0, 1.1], index=[0, 1])
        b = pd.Series([1.0, 0.9], index=[0, 1])
        published = pd.DataFrame(columns=["series_code", "period", "value"])
        coverage = {"alpha": (10, 100.0), "beta": (20, 100.0)}
        config = _config()

        forward = run_index({"alpha": a, "beta": b}, published, coverage, config, "s", "c")
        backward = run_index({"beta": b, "alpha": a}, published, coverage, config, "s", "c")

        pd.testing.assert_frame_equal(forward.index_values, backward.index_values)

    def test_a_different_config_hash_changes_the_run_hash_but_not_the_values(self) -> None:
        window_indices = {"national": pd.Series([1.0, 1.05], index=[0, 1])}
        published = pd.DataFrame(columns=["series_code", "period", "value"])
        coverage = {"national": (100, 100.0)}
        config = _config()

        run_a = run_index(window_indices, published, coverage, config, "snap-1", "cfg-a")
        run_b = run_index(window_indices, published, coverage, config, "snap-1", "cfg-b")

        assert run_a.run_hash != run_b.run_hash
        pd.testing.assert_frame_equal(run_a.index_values, run_b.index_values)


class TestRevision:
    def test_recomputing_an_already_published_period_is_recorded_as_a_revision(self) -> None:
        window_indices = {"national": pd.Series([1.0, 1.2], index=[0, 1])}
        # period 1 was already published, but at a different value than this
        # recomputation now produces (e.g. a corrected data snapshot).
        published = pd.DataFrame({"series_code": ["national"], "period": [1], "value": [999.0]})
        coverage = {"national": (50, 100.0)}
        config = _config()

        result = run_index(window_indices, published, coverage, config, "snap-4", "cfg-1")

        assert len(result.revisions) == 1
        revision = result.revisions.iloc[0]
        assert revision["series_code"] == "national"
        assert revision["period"] == 1
        assert revision["old_value"] == pytest.approx(999.0)
        assert revision["new_value"] == pytest.approx(1.2, abs=1e-9)

    def test_an_unchanged_recomputation_is_not_a_revision(self) -> None:
        window_indices = {"national": pd.Series([1.0, 1.2], index=[0, 1])}
        published = pd.DataFrame({"series_code": ["national"], "period": [1], "value": [1.2]})
        coverage = {"national": (50, 100.0)}
        config = _config()

        result = run_index(window_indices, published, coverage, config, "snap-4", "cfg-1")

        assert result.revisions.empty


class TestValidation:
    def test_empty_window_indices_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            run_index({}, pd.DataFrame(), {}, _config(), "s", "c")

    def test_missing_coverage_entry_rejected(self) -> None:
        window_indices = {"national": pd.Series([1.0, 1.1], index=[0, 1])}
        published = pd.DataFrame(columns=["series_code", "period", "value"])
        with pytest.raises(ValueError, match="coverage is missing"):
            run_index(window_indices, published, {}, _config(), "s", "c")

    def test_empty_window_index_for_a_series_is_rejected(self) -> None:
        window_indices = {"national": pd.Series([], index=[], dtype=float)}
        published = pd.DataFrame(columns=["series_code", "period", "value"])
        coverage = {"national": (10, 100.0)}
        with pytest.raises(ValueError, match="at least one period"):
            run_index(window_indices, published, coverage, _config(), "s", "c")

    def test_non_positive_window_level_is_rejected(self) -> None:
        window_indices = {"national": pd.Series([1.0, -1.0], index=[0, 1])}
        published = pd.DataFrame(columns=["series_code", "period", "value"])
        coverage = {"national": (10, 100.0)}
        with pytest.raises(ValueError, match="strictly positive"):
            run_index(window_indices, published, coverage, _config(), "s", "c")
