"""Hard-coded example payloads that freeze the API contract.

Read this before using anything it returns.

These values are **placeholders**, not measurements. No airfare has been collected yet;
nothing here has passed through a collector, a cleaner or an index run. Every payload
built from this module carries ``meta.data_status == "EXAMPLE_ONLY"`` and every response
carries the header ``X-APIx-Data-Status: EXAMPLE_ONLY``, so a consumer that wires
against this service cannot mistake a placeholder for a published statistic.

The numbers are round and obviously synthetic (100.0, 105.5, 5000.00) for the same
reason: nothing here should ever look like a plausible measurement.

Phase 3 replaces this module with database queries. The response *shapes* are the
deliverable; the values are scaffolding.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from apix_api.pagination import ResponseMeta

EXAMPLE_INDEX_RUN_ID = "00000000-0000-4000-8000-000000000001"
EXAMPLE_SNAPSHOT_ID = "00000000-0000-4000-8000-000000000002"
EXAMPLE_QUOTE_ID = "00000000-0000-4000-8000-000000000003"
EXAMPLE_CLEAN_ID = "00000000-0000-4000-8000-000000000004"
EXAMPLE_PREVIEW_RUN_ID = "00000000-0000-4000-8000-00000000000e"

# Periods used across the examples. Fixed dates, so the OpenAPI document and the
# contract tests are deterministic.
EXAMPLE_PERIODS: tuple[date, ...] = (
    date(2026, 4, 1),
    date(2026, 5, 1),
    date(2026, 6, 1),
    date(2026, 7, 1),
    date(2026, 8, 1),
)
EXAMPLE_VALUES: tuple[float, ...] = (100.0, 101.5, 103.0, 102.5, 105.5)

EXAMPLE_SERIES_CODE = "APIX.ALL.M"

# The official CPI comparison series the dashboard overlays on the headline. The code is
# part of the contract; the values served against it are placeholders like every other.
EXAMPLE_CPI_SERIES_CODE = "CPI.TRANSPORT.AIRFARE.M"


def example_offset(*parts: str, scale: float = 2.0) -> float:
    """Deterministic, obviously-synthetic offset derived from the request itself.

    Distinct requests (a different series code, a different method configuration) must
    produce visibly distinct example payloads, or the front end could not demonstrate
    that changing an input changes the output. The offset is a pure function of its
    inputs — same request, same bytes — and is quantised to 0.5 steps so the values stay
    round and recognisably fake. It is scaffolding, not simulation.
    """
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    steps = int.from_bytes(digest[:2], "big") % 17 - 8  # -8 .. +8
    return steps * 0.5 * scale / 2.0


def response_meta(
    *,
    method_version: str | None = None,
    basket_version: str | None = None,
    with_run: bool = True,
) -> ResponseMeta:
    """Metadata block stamped onto every example response."""
    return ResponseMeta(
        data_status="EXAMPLE_ONLY",
        generated_at=datetime.now(tz=UTC).isoformat(),
        method_version=method_version,
        basket_version=basket_version,
        index_run_id=EXAMPLE_INDEX_RUN_ID if with_run else None,
        snapshot_id=EXAMPLE_SNAPSHOT_ID if with_run else None,
    )
