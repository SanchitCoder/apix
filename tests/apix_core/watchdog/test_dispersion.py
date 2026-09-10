from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from apix_core.watchdog.dispersion import compute_dispersion


def _observations(*fares: float) -> pd.DataFrame:
    probed_at = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
    return pd.DataFrame(
        {
            "source_code": ["airline_indigo"] * len(fares),
            "flight_key": ["6E-123-2026-09-15"] * len(fares),
            "probed_at": [probed_at] * len(fares),
            "session_id": [f"s{i}" for i in range(len(fares))],
            "total_fare": list(fares),
        }
    )


class TestComputeDispersion:
    def test_identical_fares_give_zero_dispersion(self) -> None:
        result = compute_dispersion(_observations(4500.0, 4500.0, 4500.0))
        assert result["value"].iloc[0] == pytest.approx(0.0)
        assert result["n_sessions"].iloc[0] == 3

    def test_a_single_session_has_a_defined_zero_dispersion(self) -> None:
        result = compute_dispersion(_observations(4500.0))
        assert result["value"].iloc[0] == 0.0
        assert result["n_sessions"].iloc[0] == 1

    def test_dispersion_reflects_real_spread(self) -> None:
        result = compute_dispersion(_observations(4000.0, 5000.0, 4500.0))
        assert result["value"].iloc[0] > 0.0
        assert result["min_fare"].iloc[0] == 4000.0
        assert result["max_fare"].iloc[0] == 5000.0

    def test_missing_columns_is_a_value_error(self) -> None:
        with pytest.raises(ValueError, match="missing required columns"):
            compute_dispersion(pd.DataFrame({"source_code": ["x"]}))

    def test_non_positive_fare_is_a_value_error(self) -> None:
        with pytest.raises(ValueError, match="strictly positive"):
            compute_dispersion(_observations(0.0, 100.0))
