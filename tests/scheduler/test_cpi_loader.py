"""The CPI air-fare index loader's parsing logic. All values here are FAKE (see
docs/data-sources.md) — no real MoSPI CPI release is loaded anywhere in tests.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apix_scheduler.cpi_loader import CpiLoadError, read_extract


def _write(path, lines: list[str]) -> None:
    path.write_text(
        "# FAKE fixture data for tests — not a real MoSPI release\n" + "\n".join(lines) + "\n",
        encoding="utf-8",
    )


class TestReadExtract:
    def test_parses_a_well_formed_extract(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(path, ["period,value,base_year,release_date", "2026-07,142.3,2011-12,2026-08-12"])
        rows = read_extract(path)
        assert len(rows) == 1
        assert rows[0].period == date(2026, 7, 1)
        assert rows[0].value == Decimal("142.300000")
        assert rows[0].base_year == "2011-12"
        assert rows[0].release_date == date(2026, 8, 12)

    def test_missing_columns_is_a_load_error(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(path, ["period,value", "2026-07,142.3"])
        with pytest.raises(CpiLoadError, match="expected columns"):
            read_extract(path)

    def test_bad_period_is_a_load_error(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(path, ["period,value,base_year,release_date", "July,142.3,2011-12,2026-08-12"])
        with pytest.raises(CpiLoadError, match="bad period"):
            read_extract(path)

    def test_non_positive_value_is_a_load_error(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(path, ["period,value,base_year,release_date", "2026-07,0,2011-12,2026-08-12"])
        with pytest.raises(CpiLoadError, match="must be positive"):
            read_extract(path)

    def test_bad_release_date_is_a_load_error(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(path, ["period,value,base_year,release_date", "2026-07,142.3,2011-12,Aug 2026"])
        with pytest.raises(CpiLoadError, match="bad release_date"):
            read_extract(path)

    def test_empty_extract_is_a_load_error(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(path, ["period,value,base_year,release_date"])
        with pytest.raises(CpiLoadError, match="no data rows"):
            read_extract(path)
