"""Nowcast config: hashable, and the regression must keep real degrees of freedom."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apix_core.config import NowcastConfigFile, config_hash, load_nowcast
from apix_core.config.nowcast import BridgeModelKind


def _nowcast(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": "test",
        "bridge_model": {
            "kind": "ols_lagged",
            "n_apix_lags": 2,
            "n_cpi_lags": 1,
            "min_observations": 24,
        },
        "atf_passthrough": {"max_lag": 6, "min_observations": 24},
        "movement_decomposition": {},
    }
    payload.update(overrides)
    return payload


class TestShippedNowcast:
    def test_the_real_nowcast_file_validates(self, config_dir) -> None:
        nowcast = load_nowcast(config_dir)
        assert nowcast.bridge_model.kind is BridgeModelKind.OLS_LAGGED

    def test_hash_is_stable_across_loads(self, config_dir) -> None:
        assert config_hash(load_nowcast(config_dir)) == config_hash(load_nowcast(config_dir))


class TestBridgeModelValidation:
    def test_too_few_min_observations_for_the_lag_structure_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="min_observations"):
            NowcastConfigFile.model_validate(
                _nowcast(
                    bridge_model={
                        "kind": "ols_lagged",
                        "n_apix_lags": 4,
                        "n_cpi_lags": 4,
                        "min_observations": 8,
                    }
                )
            )

    def test_midas_is_an_accepted_config_value(self) -> None:
        """The schema states the growth path; only fit_bridge_model refuses MIDAS."""
        cfg = NowcastConfigFile.model_validate(
            _nowcast(
                bridge_model={
                    "kind": "midas",
                    "n_apix_lags": 2,
                    "n_cpi_lags": 1,
                    "min_observations": 24,
                }
            )
        )
        assert cfg.bridge_model.kind is BridgeModelKind.MIDAS

    def test_unknown_keys_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            NowcastConfigFile.model_validate(_nowcast(extra_field="nope"))


class TestAtfPassThroughValidation:
    def test_too_few_min_observations_for_max_lag_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="min_observations"):
            NowcastConfigFile.model_validate(
                _nowcast(atf_passthrough={"max_lag": 10, "min_observations": 8})
            )
