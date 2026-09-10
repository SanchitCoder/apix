"""config/cleaning.yaml governs apix_core.clean; it is validated like every other file."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apix_core.config import CleaningConfig, config_hash, load_cleaning
from apix_core.config.cleaning import OutlierRuleName


def _cleaning(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": "test",
        "dedup": {"dep_time_tolerance_minutes": 15},
        "decomposition": {"tax_rate": 0.05},
        "outliers": {
            "active_rule": "mad_log",
            "mad_threshold": 3.5,
            "iqr_k": 1.5,
            "min_cell_size": 5,
        },
        "imputation": {
            "sellout_group_columns": ["route_id", "advance_days", "carrier_type"],
            "min_group_size": 3,
        },
        "quality_gates": {
            "distance_bands": [
                {
                    "name": "short",
                    "max_km": 600,
                    "base_fare_min_inr": 500,
                    "base_fare_max_inr": 25000,
                },
                {
                    "name": "long",
                    "max_km": None,
                    "base_fare_min_inr": 1200,
                    "base_fare_max_inr": 60000,
                },
            ],
            "tax_share_min": 0.01,
            "tax_share_max": 0.2,
            "coverage_floor_pct": 40.0,
        },
    }
    payload.update(overrides)
    return payload


class TestShippedCleaning:
    def test_the_real_cleaning_file_validates(self, config_dir) -> None:
        cleaning = load_cleaning(config_dir)
        assert cleaning.version == "2026.1"
        assert cleaning.outliers.active_rule is OutlierRuleName.MAD_LOG

    def test_hash_is_stable_across_loads(self, config_dir) -> None:
        assert config_hash(load_cleaning(config_dir)) == config_hash(load_cleaning(config_dir))


class TestDistanceBands:
    def test_band_lookup_picks_the_narrowest_matching_band(self, config_dir) -> None:
        gates = load_cleaning(config_dir).quality_gates
        assert gates.band_for_distance(100).name == "short"
        assert gates.band_for_distance(3000).name == "long"

    def test_requires_exactly_one_unbounded_band(self) -> None:
        payload = _cleaning()
        gates = dict(payload["quality_gates"])  # type: ignore[arg-type]
        gates["distance_bands"] = [
            {"name": "short", "max_km": 600, "base_fare_min_inr": 500, "base_fare_max_inr": 25000},
        ]
        payload["quality_gates"] = gates
        with pytest.raises(ValidationError, match="exactly one unbounded"):
            CleaningConfig.model_validate(payload)

    def test_unbounded_band_must_be_last(self) -> None:
        payload = _cleaning()
        gates = dict(payload["quality_gates"])  # type: ignore[arg-type]
        gates["distance_bands"] = [
            {"name": "long", "max_km": None, "base_fare_min_inr": 1200, "base_fare_max_inr": 60000},
            {"name": "short", "max_km": 600, "base_fare_min_inr": 500, "base_fare_max_inr": 25000},
        ]
        payload["quality_gates"] = gates
        with pytest.raises(ValidationError, match="unbounded distance band must be listed last"):
            CleaningConfig.model_validate(payload)

    def test_bands_must_increase(self) -> None:
        payload = _cleaning()
        gates = dict(payload["quality_gates"])  # type: ignore[arg-type]
        gates["distance_bands"] = [
            {"name": "a", "max_km": 1500, "base_fare_min_inr": 500, "base_fare_max_inr": 25000},
            {"name": "b", "max_km": 600, "base_fare_min_inr": 500, "base_fare_max_inr": 25000},
            {"name": "c", "max_km": None, "base_fare_min_inr": 1200, "base_fare_max_inr": 60000},
        ]
        payload["quality_gates"] = gates
        with pytest.raises(ValidationError, match="increasing max_km order"):
            CleaningConfig.model_validate(payload)

    def test_band_bounds_must_be_ordered(self) -> None:
        payload = _cleaning()
        gates = dict(payload["quality_gates"])  # type: ignore[arg-type]
        gates["distance_bands"] = [
            {"name": "bad", "max_km": None, "base_fare_min_inr": 5000, "base_fare_max_inr": 1000},
        ]
        payload["quality_gates"] = gates
        with pytest.raises(ValidationError, match="base_fare_max_inr must exceed"):
            CleaningConfig.model_validate(payload)


class TestQualityGateValidation:
    def test_tax_share_max_must_exceed_min(self) -> None:
        payload = _cleaning()
        gates = dict(payload["quality_gates"])  # type: ignore[arg-type]
        gates["tax_share_min"] = 0.5
        gates["tax_share_max"] = 0.1
        payload["quality_gates"] = gates
        with pytest.raises(ValidationError, match="tax_share_max must exceed"):
            CleaningConfig.model_validate(payload)

    def test_unknown_keys_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CleaningConfig.model_validate(_cleaning(unexpected="nope"))
