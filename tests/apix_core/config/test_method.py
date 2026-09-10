"""The method file is hashed, and biased formulae cannot be published."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apix_core.config import MethodConfigFile, config_hash, load_method
from apix_core.config.method import ElementaryFormula


def _method(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "method_version": "test",
        "price_reference_period": "2026-01",
        "elementary_formula": "jevons",
        "multilateral_method": "geks_tornqvist",
        "window": {"length_periods": 13, "frequency": "M"},
        "splice_method": "movement",
        "quality_adjustment": {"enabled": True, "columns": ["stops"]},
        "booking_profile": {"source": "test fixture", "weights": {"AP00_03": 1.0}},
        "imputation_rule": "targeted_mean",
        "outlier_rules": [],
    }
    payload.update(overrides)
    return payload


class TestShippedMethod:
    def test_the_real_method_file_validates(self, config_dir) -> None:
        method = load_method(config_dir)
        assert method.method_version == "2026.1"
        assert method.elementary_formula is ElementaryFormula.JEVONS

    def test_booking_profile_windows_match_the_basket(self, config_dir) -> None:
        """The booking-profile weights must key on the advance windows that actually
        exist — a typo here would silently drop a window's weight rather than fail.
        """
        from apix_core.config import load_basket

        basket_codes = {w.code for w in load_basket(config_dir).advance_windows}
        method = load_method(config_dir)
        assert set(method.booking_profile.weights) == basket_codes

    def test_quality_adjustment_columns_exist_on_the_clean_table(self, config_dir) -> None:
        """A hedonic characteristic must be a column we actually store.

        Catches a method change that names a characteristic no collector produces —
        which would otherwise surface as a KeyError deep inside an index run.
        """
        from apix_core.models import FareQuoteClean

        available = set(FareQuoteClean.__table__.columns.keys())
        for column in load_method(config_dir).quality_adjustment.columns:
            assert column in available, f"{column!r} is not a column on fare_quote_clean"


class TestMethodHashing:
    def test_hash_is_stable_across_loads(self, config_dir) -> None:
        assert config_hash(load_method(config_dir)) == config_hash(load_method(config_dir))

    def test_hash_changes_when_a_value_changes(self) -> None:
        base = MethodConfigFile.model_validate(_method())
        changed = MethodConfigFile.model_validate(_method(min_quotes_per_cell=7))
        assert config_hash(base) != config_hash(changed)

    def test_hash_is_a_sha256_hex_digest(self, config_dir) -> None:
        digest = config_hash(load_method(config_dir))
        assert len(digest) == 64
        assert set(digest) <= set("0123456789abcdef")


class TestMethodValidation:
    def test_carli_cannot_be_published(self) -> None:
        """Carli is upward-biased and fails time reversal; it must not be the method."""
        with pytest.raises(ValidationError, match="carli is not permitted"):
            MethodConfigFile.model_validate(_method(elementary_formula="carli"))

    def test_duplicate_outlier_rule_names_are_rejected(self) -> None:
        rule = {"name": "dupe", "method": "mad", "threshold": 5.0}
        with pytest.raises(ValidationError, match="duplicate outlier rule names"):
            MethodConfigFile.model_validate(_method(outlier_rules=[rule, rule]))

    def test_unknown_keys_are_rejected(self) -> None:
        """extra='forbid' everywhere: a typo in the method file is a failure, not a no-op."""
        with pytest.raises(ValidationError):
            MethodConfigFile.model_validate(_method(elementry_formula="jevons"))

    def test_malformed_reference_period_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MethodConfigFile.model_validate(_method(price_reference_period="Jan 2026"))

    def test_window_shorter_than_two_periods_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MethodConfigFile.model_validate(_method(window={"length_periods": 1}))
