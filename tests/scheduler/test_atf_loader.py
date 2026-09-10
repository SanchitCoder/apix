"""The ATF price loader's parsing logic. All prices here are FAKE (see
docs/data-sources.md) — no real ATF price notification is loaded anywhere in tests.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apix_scheduler.atf_loader import AtfLoadError, read_extract


def _write(path, lines: list[str]) -> None:
    path.write_text(
        "# FAKE fixture data for tests — not a real ATF notification\n" + "\n".join(lines) + "\n",
        encoding="utf-8",
    )


class TestReadExtract:
    def test_parses_a_well_formed_extract(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(
            path,
            [
                "price_date,city,price_per_kl",
                "2026-09-01,Delhi,98765.43",
                "2026-09-01,Mumbai,97654.32",
            ],
        )
        rows = read_extract(path)
        assert len(rows) == 2
        assert rows[0].price_date == date(2026, 9, 1)
        assert rows[0].city == "Delhi"
        assert rows[0].price_per_kl == Decimal("98765.43")

    def test_missing_columns_is_a_load_error(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(path, ["price_date,city", "2026-09-01,Delhi"])
        with pytest.raises(AtfLoadError, match="expected columns"):
            read_extract(path)

    def test_bad_date_is_a_load_error(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(path, ["price_date,city,price_per_kl", "Sept 1 2026,Delhi,98765.43"])
        with pytest.raises(AtfLoadError, match="bad price_date"):
            read_extract(path)

    def test_non_positive_price_is_a_load_error(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(path, ["price_date,city,price_per_kl", "2026-09-01,Delhi,0"])
        with pytest.raises(AtfLoadError, match="must be positive"):
            read_extract(path)

    def test_empty_extract_is_a_load_error(self, tmp_path) -> None:
        path = tmp_path / "extract.csv"
        _write(path, ["price_date,city,price_per_kl"])
        with pytest.raises(AtfLoadError, match="no data rows"):
            read_extract(path)
