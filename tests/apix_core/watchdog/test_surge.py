from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from apix_core.config.watchdog import SurgeConfig
from apix_core.watchdog.surge import detect_surges


def _config(**overrides: object) -> SurgeConfig:
    payload: dict[str, object] = {
        "baseline_window_days": 14,
        "band_width_k": 3.0,
        "min_history_periods": 5,
    }
    payload.update(overrides)
    return SurgeConfig.model_validate(payload)


def _fares(route: str, fares: list[float], start: date = date(2026, 8, 1)) -> pd.DataFrame:
    dates = [start + timedelta(days=i) for i in range(len(fares))]
    return pd.DataFrame({"route_code": [route] * len(fares), "travel_date": dates, "fare": fares})


class TestDetectSurges:
    def test_insufficient_history_is_not_flagged(self) -> None:
        result = detect_surges(_fares("DEL-BOM", [100.0, 101.0, 99.0]), _config())
        assert not result["baseline_available"].any()
        assert not result["is_surge"].any()

    def test_a_stable_series_is_never_flagged(self) -> None:
        fares = [100.0 + (i % 3) for i in range(30)]
        result = detect_surges(_fares("DEL-BOM", fares), _config())
        assert not result["is_surge"].any()

    def test_a_sharp_jump_is_flagged(self) -> None:
        fares = [100.0 + (i % 3) for i in range(25)] + [500.0]
        result = detect_surges(_fares("DEL-BOM", fares), _config())
        assert bool(result["is_surge"].iloc[-1]) is True

    def test_routes_are_baselined_independently(self) -> None:
        stable = _fares("DEL-BOM", [100.0 + (i % 3) for i in range(20)])
        other = _fares("BOM-DEL", [900.0 + (i % 3) for i in range(20)])
        combined = pd.concat([stable, other], ignore_index=True)
        result = detect_surges(combined, _config())
        assert not result["is_surge"].any()

    def test_missing_columns_is_a_value_error(self) -> None:
        with pytest.raises(ValueError, match="missing required columns"):
            detect_surges(pd.DataFrame({"route_code": ["DEL-BOM"]}), _config())

    def test_non_positive_fare_is_a_value_error(self) -> None:
        with pytest.raises(ValueError, match="strictly positive"):
            detect_surges(_fares("DEL-BOM", [0.0, 100.0]), _config())
