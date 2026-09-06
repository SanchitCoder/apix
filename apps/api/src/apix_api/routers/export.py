"""/v1/export.csv — a flat download of a series.

CSV because the statisticians who will check this work live in spreadsheets. The header
row is part of the contract and the file is streamed, so a multi-year request does not
have to be materialised in memory.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from apix_api.errors import ERROR_RESPONSES
from apix_api.examples import (
    EXAMPLE_INDEX_RUN_ID,
    EXAMPLE_PERIODS,
    EXAMPLE_SERIES_CODE,
    EXAMPLE_VALUES,
)

router = APIRouter(prefix="/v1", tags=["export"], responses=ERROR_RESPONSES)

CSV_COLUMNS = (
    "series",
    "period",
    "value",
    "n_quotes",
    "coverage_pct",
    "is_imputed",
    "status",
    "index_run_id",
    "data_status",
)


def _rows(series: str) -> Iterator[list[str]]:
    """Yield the header and then one row per observation."""
    yield list(CSV_COLUMNS)
    for period, value in zip(EXAMPLE_PERIODS, EXAMPLE_VALUES, strict=True):
        yield [
            series,
            period.isoformat(),
            f"{value:.6f}",
            "12500",
            "96.00",
            "false",
            "EXAMPLE_ONLY",
            EXAMPLE_INDEX_RUN_ID,
            "EXAMPLE_ONLY",
        ]


def _stream(series: str) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in _rows(series):
        writer.writerow(row)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


@router.get(
    "/export.csv",
    summary="Download a series as CSV",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "CSV with a fixed header row.",
            "content": {"text/csv": {"schema": {"type": "string"}}},
        }
    },
)
async def export_csv(
    series: Annotated[str, Query(max_length=64, examples=["APIX.ALL.M"])] = EXAMPLE_SERIES_CODE,
    from_: Annotated[date | None, Query(alias="from", description="Inclusive start.")] = None,
    to: Annotated[date | None, Query(description="Inclusive end.")] = None,
) -> StreamingResponse:
    """Stream a series as CSV.

    Every row carries ``index_run_id`` and ``data_status``, so a downloaded file remains
    traceable once it has left the API and is sitting in someone's spreadsheet.
    """
    filename = f"apix_{series.replace('.', '_')}.csv"
    return StreamingResponse(
        _stream(series),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-APIx-Data-Status": "EXAMPLE_ONLY",
        },
    )
