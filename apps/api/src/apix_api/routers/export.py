"""/v1/export.csv — a flat download of a series.

CSV because the statisticians who will check this work live in spreadsheets. The header
row is part of the contract and the file is streamed, so a multi-year request does not
have to be materialised in memory. Microdata-adjacent: requires a researcher or official
API key, same as the other drill-down endpoints.
"""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator, Iterator
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from apix_api.auth import RoleDep, require_authenticated
from apix_api.db import SessionDep  # noqa: TC001
from apix_api.errors import MICRODATA_ERROR_RESPONSES
from apix_api.queries import LatestValueRow, get_series_id, latest_values

router = APIRouter(
    prefix="/v1",
    tags=["export"],
    responses=MICRODATA_ERROR_RESPONSES,
    dependencies=[Depends(require_authenticated)],
)

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


def _rows(series: str, values: list[LatestValueRow]) -> Iterator[list[str]]:
    yield list(CSV_COLUMNS)
    for row in values:
        released = row["released_at"] is not None
        yield [
            series,
            row["period"].isoformat(),
            f"{float(row['value']):.6f}",
            str(int(row["n_quotes"])),
            f"{float(row['coverage_pct']):.2f}" if row["coverage_pct"] is not None else "",
            "false",
            "PUBLISHED" if released else "PROVISIONAL",
            str(row["index_run_id"]),
            "PUBLISHED" if released else "PROVISIONAL",
        ]


async def _stream(series: str, values: list[LatestValueRow]) -> AsyncIterator[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in _rows(series, values):
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
    session: SessionDep,
    role: RoleDep,
    series: Annotated[str, Query(max_length=64, examples=["APIX.ALL.M"])] = "APIX.ALL.M",
    from_: Annotated[date | None, Query(alias="from", description="Inclusive start.")] = None,
    to: Annotated[date | None, Query(description="Inclusive end.")] = None,
) -> StreamingResponse:
    """Stream a series as CSV.

    Every row carries ``index_run_id`` and ``data_status``, so a downloaded file remains
    traceable once it has left the API and is sitting in someone's spreadsheet.
    """
    series_id = await get_series_id(session, series)
    if series_id is None:
        raise HTTPException(status_code=404, detail=f"no series is published with code {series!r}")
    values = await latest_values(session, series_id, role=role, from_period=from_, to_period=to)

    filename = f"apix_{series.replace('.', '_')}.csv"
    return StreamingResponse(
        _stream(series, values),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
