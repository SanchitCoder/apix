"""Watchdog config: the probe frequency ceiling is enforced by the schema itself."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apix_core.config import WatchdogConfigFile, config_hash, load_watchdog


def _watchdog(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": "test",
        "personalisation_probe": {
            "n_sessions": 4,
            "cookie_states": ["none", "existing_thin"],
            "ua_classes": ["desktop_chrome"],
            "geographies": ["in_delhi"],
            "routes": ["DEL-BOM"],
            "max_runs_per_day": 2,
            "min_interval_hours": 12.0,
        },
        "surge": {"baseline_window_days": 90, "band_width_k": 3.0, "min_history_periods": 14},
        "sellout": {"lookback_days": 30, "min_group_size": 5},
        "rail": {"enabled": False, "corridor_map": {}},
    }
    payload.update(overrides)
    return payload


class TestShippedWatchdog:
    def test_the_real_watchdog_file_validates(self, config_dir) -> None:
        watchdog = load_watchdog(config_dir)
        assert watchdog.personalisation_probe.max_runs_per_day <= 6

    def test_hash_is_stable_across_loads(self, config_dir) -> None:
        assert config_hash(load_watchdog(config_dir)) == config_hash(load_watchdog(config_dir))


class TestPersonalisationProbeValidation:
    def test_max_runs_per_day_ceiling_is_enforced(self) -> None:
        with pytest.raises(ValidationError):
            WatchdogConfigFile.model_validate(
                _watchdog(
                    personalisation_probe={
                        "n_sessions": 4,
                        "cookie_states": ["none"],
                        "ua_classes": ["desktop_chrome"],
                        "geographies": ["in_delhi"],
                        "routes": ["DEL-BOM"],
                        "max_runs_per_day": 7,
                        "min_interval_hours": 1.0,
                    }
                )
            )

    def test_schedule_that_does_not_fit_in_a_day_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exceeds 24 hours"):
            WatchdogConfigFile.model_validate(
                _watchdog(
                    personalisation_probe={
                        "n_sessions": 2,
                        "cookie_states": ["none", "existing_thin"],
                        "ua_classes": ["desktop_chrome"],
                        "geographies": ["in_delhi"],
                        "routes": ["DEL-BOM"],
                        "max_runs_per_day": 6,
                        "min_interval_hours": 6.0,
                    }
                )
            )

    def test_n_sessions_exceeding_profile_combinations_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="n_sessions"):
            WatchdogConfigFile.model_validate(
                _watchdog(
                    personalisation_probe={
                        "n_sessions": 5,
                        "cookie_states": ["none"],
                        "ua_classes": ["desktop_chrome"],
                        "geographies": ["in_delhi"],
                        "routes": ["DEL-BOM"],
                        "max_runs_per_day": 1,
                        "min_interval_hours": 24.0,
                    }
                )
            )

    def test_unknown_keys_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WatchdogConfigFile.model_validate(_watchdog(extra_field="nope"))
