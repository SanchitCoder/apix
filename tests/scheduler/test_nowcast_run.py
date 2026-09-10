"""nowcast_run's DB-free helpers: vintage-safe vintage collapse and period parsing."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from apix_scheduler.nowcast_run import _latest_by_period_as_of, _parse_period


def _frame(rows: list[tuple[date, float, datetime]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["period", "value", "collected_at"])


class TestParsePeriod:
    def test_parses_year_month(self) -> None:
        assert _parse_period("2026-09") == date(2026, 9, 1)


class TestLatestByPeriodAsOf:
    def test_empty_frame_gives_an_empty_result(self) -> None:
        result = _latest_by_period_as_of(_frame([]), date(2026, 9, 1), "value", "collected_at")
        assert result.empty
        assert list(result.columns) == ["period", "value", "collected_at"]

    def test_picks_the_latest_vintage_knowable_as_of(self) -> None:
        period = date(2026, 7, 1)
        rows = [
            (period, 100.0, datetime(2026, 8, 5, tzinfo=UTC)),  # first publication
            (period, 101.0, datetime(2026, 9, 1, tzinfo=UTC)),  # a later revision
        ]
        # as_of before the revision -> only the first publication is knowable
        early = _latest_by_period_as_of(_frame(rows), date(2026, 8, 20), "value", "collected_at")
        assert early["value"].iloc[0] == pytest.approx(100.0)
        # as_of after the revision -> the revision is what's knowable
        late = _latest_by_period_as_of(_frame(rows), date(2026, 9, 5), "value", "collected_at")
        assert late["value"].iloc[0] == pytest.approx(101.0)

    def test_a_period_with_no_vintage_knowable_yet_is_excluded(self) -> None:
        rows = [(date(2026, 7, 1), 100.0, datetime(2026, 9, 1, tzinfo=UTC))]
        result = _latest_by_period_as_of(_frame(rows), date(2026, 8, 1), "value", "collected_at")
        assert result.empty
