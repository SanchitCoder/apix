"""There is no vintage-store table: this is the filter over the existing append-only
data that makes point-in-time correctness possible. Look-ahead bias is the failure
mode CLAUDE.md calls out as the one that would discredit the whole project.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from apix_core.nowcast.vintage import VintageViolationError, assert_no_look_ahead, filter_as_of


def _frame(*collected_at: datetime) -> pd.DataFrame:
    return pd.DataFrame({"value": range(len(collected_at)), "collected_at": list(collected_at)})


class TestFilterAsOf:
    def test_keeps_rows_at_or_before_as_of(self) -> None:
        df = _frame(
            datetime(2026, 9, 1, tzinfo=UTC),
            datetime(2026, 9, 5, tzinfo=UTC),
            datetime(2026, 9, 10, tzinfo=UTC),
        )
        result = filter_as_of(df, datetime(2026, 9, 5, tzinfo=UTC))
        assert list(result["value"]) == [0, 1]

    def test_empty_result_for_an_as_of_before_any_data_is_not_an_error(self) -> None:
        df = _frame(datetime(2026, 9, 1, tzinfo=UTC))
        result = filter_as_of(df, datetime(2026, 1, 1, tzinfo=UTC))
        assert result.empty

    def test_missing_timestamp_column_is_a_value_error(self) -> None:
        with pytest.raises(ValueError, match="collected_at"):
            filter_as_of(pd.DataFrame({"value": [1]}), date(2026, 9, 1))


class TestAssertNoLookAhead:
    def test_passes_when_every_row_is_on_or_before_as_of(self) -> None:
        df = _frame(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 5, tzinfo=UTC))
        assert_no_look_ahead(df, datetime(2026, 9, 5, tzinfo=UTC))  # does not raise

    def test_raises_when_any_row_is_after_as_of(self) -> None:
        """The required look-ahead test: a training set containing so much as one
        observation collected after the nowcast date must fail, not fit silently.
        """
        df = _frame(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 11, tzinfo=UTC))
        with pytest.raises(VintageViolationError, match="1 row"):
            assert_no_look_ahead(df, datetime(2026, 9, 5, tzinfo=UTC))

    def test_empty_frame_passes(self) -> None:
        assert_no_look_ahead(_frame(), datetime(2026, 9, 5, tzinfo=UTC))

    def test_missing_timestamp_column_is_a_value_error(self) -> None:
        with pytest.raises(ValueError, match="collected_at"):
            assert_no_look_ahead(pd.DataFrame({"value": [1]}), date(2026, 9, 1))
