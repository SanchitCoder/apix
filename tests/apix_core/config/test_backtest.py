"""Back-test config: the reporting window has a hard 30-day floor."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apix_core.config import BacktestConfigFile, config_hash, load_backtest


def _backtest(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": "test",
        "reporting_window_days": 90,
        "min_periods_for_correlation": 5,
    }
    payload.update(overrides)
    return payload


class TestShippedBacktest:
    def test_the_real_backtest_file_validates(self, config_dir) -> None:
        backtest = load_backtest(config_dir)
        assert backtest.reporting_window_days >= 30

    def test_hash_is_stable_across_loads(self, config_dir) -> None:
        assert config_hash(load_backtest(config_dir)) == config_hash(load_backtest(config_dir))


class TestBacktestValidation:
    def test_reporting_window_below_thirty_days_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BacktestConfigFile.model_validate(_backtest(reporting_window_days=29))

    def test_default_routes_is_empty_meaning_all_basket_routes(self) -> None:
        cfg = BacktestConfigFile.model_validate(_backtest())
        assert cfg.routes == []

    def test_unknown_keys_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BacktestConfigFile.model_validate(_backtest(extra_field="nope"))
