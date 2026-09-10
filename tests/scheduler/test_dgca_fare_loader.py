"""The DGCA average-fare loader's parsing logic. All fares here are FAKE, chosen only
to exercise validation — no real DGCA fare figure exists anywhere in this repository
(see docs/data-sources.md); a real extract is loaded by a human.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apix_scheduler.dgca_fare_loader import DgcaFareLoadError, read_extract


def _write(path, lines: list[str]) -> None:
    path.write_text(
        "# FAKE fixture data for tests — not a real benchmark release\n" + "\n".join(lines) + "\n",
        encoding="utf-8",
    )


class TestReadExtract:
    def test_parses_a_well_formed_extract(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(
            path, ["route_code,period,avg_fare", "DEL-BOM,2026-07,5432.10", "BOM-DEL,2026-07,5310"]
        )
        rows = read_extract(path)
        assert len(rows) == 2
        assert rows[0].route_code == "DEL-BOM"
        assert rows[0].period == date(2026, 7, 1)
        assert rows[0].avg_fare == Decimal("5432.10")
        assert rows[1].avg_fare == Decimal("5310.00")

    def test_missing_columns_is_a_load_error(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(path, ["route_code,avg_fare", "DEL-BOM,5432.10"])
        with pytest.raises(DgcaFareLoadError, match="expected columns"):
            read_extract(path)

    def test_bad_period_is_a_load_error(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(path, ["route_code,period,avg_fare", "DEL-BOM,July 2026,5432.10"])
        with pytest.raises(DgcaFareLoadError, match="bad period"):
            read_extract(path)

    def test_non_positive_fare_is_a_load_error(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(path, ["route_code,period,avg_fare", "DEL-BOM,2026-07,0"])
        with pytest.raises(DgcaFareLoadError, match="must be positive"):
            read_extract(path)

    def test_duplicate_row_is_a_load_error(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(
            path,
            [
                "route_code,period,avg_fare",
                "DEL-BOM,2026-07,5432.10",
                "DEL-BOM,2026-07,5555.00",
            ],
        )
        with pytest.raises(DgcaFareLoadError, match="duplicate row"):
            read_extract(path)

    def test_empty_extract_is_a_load_error(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(path, ["route_code,period,avg_fare"])
        with pytest.raises(DgcaFareLoadError, match="no data rows"):
            read_extract(path)
