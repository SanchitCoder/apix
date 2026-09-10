"""/v1/sdmx — SDMX-JSON 2.0 endpoints.

SDMX is how a national statistics office consumes a series. MoSPI and the RBI ingest
SDMX, so the statistical endpoints speak SDMX-JSON 2.0.0 natively. The dataflow/DSD
shape here follows general SDMX 2.0 CPI-style conventions — see docs/sdmx.md for what
that means in practice and for the mapping notes toward MoSPI's eSankhyiki portal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, HTTPException, Path, Request, Response

from apix_api.auth import RoleDep  # noqa: TC001
from apix_api.cache import build_key, cache_get_json, cache_set_json
from apix_api.db import SessionDep  # noqa: TC001
from apix_api.errors import ERROR_RESPONSES
from apix_api.queries import get_series_id, latest_run_fingerprint, latest_values
from apix_api.schemas import SdmxMessage
from apix_core.config import load_basket
from apix_core.settings import get_settings

router = APIRouter(prefix="/v1/sdmx", tags=["sdmx"], responses=ERROR_RESPONSES)

SDMX_MEDIA_TYPE = "application/vnd.sdmx.data+json;version=2.0.0"

AGENCY_ID = "IN_APIX"
DATAFLOW_ID = "DF_AIRFARE_INDEX"
DATAFLOW_VERSION = "1.0.0"


def _series_code_for_key(route: str, carrier_type: str, ap_window: str) -> str:
    """Resolve an SDMX key's dimension values to one APIx series code.

    A key naming more than one non-``ALL`` dimension (a specific route *and* a specific
    carrier type, say) resolves to the first of route > carrier_type > ap_window —
    APIx does not publish that finer cross-cut as its own series today.
    """
    if route != "ALL":
        return f"APIX.ROUTE.{route}.M"
    if carrier_type != "ALL":
        return f"APIX.CARRIERTYPE.{carrier_type}.M"
    if ap_window != "ALL":
        return f"APIX.WINDOW.{ap_window}.M"
    return "APIX.ALL.M"


@router.get(
    "/data/{flow_ref}/{key}",
    summary="SDMX-JSON 2.0 data message",
    response_model=SdmxMessage,
    responses={
        200: {
            "description": "An SDMX-JSON 2.0.0 data message.",
            "content": {SDMX_MEDIA_TYPE: {}},
        }
    },
)
async def get_sdmx_data(
    request: Request,
    session: SessionDep,
    role: RoleDep,
    flow_ref: Annotated[
        str,
        Path(
            description=(
                "Dataflow reference, `agencyId,dataflowId,version`, "
                "e.g. `IN_APIX,DF_AIRFARE_INDEX,1.0.0`."
            ),
            examples=["IN_APIX,DF_AIRFARE_INDEX,1.0.0"],
        ),
    ],
    key: Annotated[
        str,
        Path(
            description=(
                "Series key: dimension values in DSD order, dot-separated. "
                "`M.ALL.ALL.ALL` is FREQ.ROUTE.CARRIER_TYPE.AP_WINDOW."
            ),
            examples=["M.ALL.ALL.ALL"],
        ),
    ],
    response: Response,
) -> SdmxMessage:
    """Serve one dataflow as an SDMX-JSON 2.0.0 data message.

    The observation attributes carry ``OBS_STATUS`` and the count of underlying quotes,
    so provenance survives the translation into SDMX rather than being dropped at the
    boundary.
    """
    response.headers["Content-Type"] = SDMX_MEDIA_TYPE

    parts = key.split(".")
    if len(parts) != 4:
        raise HTTPException(
            status_code=400,
            detail="key must be FREQ.ROUTE.CARRIER_TYPE.AP_WINDOW, dot-separated",
        )
    _freq, route, carrier_type, ap_window = parts
    series_code = _series_code_for_key(route, carrier_type, ap_window)

    series_id = await get_series_id(session, series_code)
    if series_id is None:
        raise HTTPException(status_code=404, detail=f"no series is published for key {key!r}")

    # Cached (apix_api.cache) keyed on the series' latest visible run: a new index run
    # invalidates naturally. Only the DB-derived arrays are cached, never `meta.prepared`
    # — a cache hit must still report the moment *this* message was assembled.
    run_fingerprint = await latest_run_fingerprint(session, [series_id], role=role)
    cache_key = build_key("sdmx", series=series_code, role=role.value, run=run_fingerprint)
    redis = request.app.state.cache_redis
    cached = cast("dict[str, Any] | None", await cache_get_json(redis, cache_key))

    if cached is not None:
        observations = cached["observations"]
        n_quotes_values = cached["n_quotes_values"]
        time_period_values = cached["time_period_values"]
    else:
        rows = await latest_values(session, series_id, role=role)
        observations = {
            str(i): [float(row["value"]), 0 if row["released_at"] is not None else 1, i]
            for i, row in enumerate(rows)
        }
        n_quotes_values = [
            {"id": str(int(row["n_quotes"])), "name": str(int(row["n_quotes"]))} for row in rows
        ]
        time_period_values = [
            {"id": row["period"].strftime("%Y-%m"), "name": row["period"].strftime("%Y-%m")}
            for row in rows
        ]
        await cache_set_json(
            redis,
            cache_key,
            {
                "observations": observations,
                "n_quotes_values": n_quotes_values,
                "time_period_values": time_period_values,
            },
            ttl_s=get_settings().api_cache_ttl_s,
        )

    basket = load_basket()

    return SdmxMessage(
        meta={
            "schema": (
                "https://raw.githubusercontent.com/sdmx-twg/sdmx-json/master/"
                "data-message/tools/schemas/2.0.0/sdmx-json-data-schema.json"
            ),
            "id": f"APIX-{series_code}",
            "prepared": datetime.now(tz=UTC).isoformat(),
            "test": False,
            "contentLanguages": ["en"],
            "sender": {"id": AGENCY_ID, "name": "APIx — Airfare Price Index for India"},
            "apix": {"requestedFlowRef": flow_ref, "key": key, "resolvedSeries": series_code},
        },
        data={
            "dataSets": [
                {
                    "action": "Information",
                    "structure": 0,
                    "series": {"0:0:0:0": {"attributes": [0], "observations": observations}},
                }
            ],
            "structures": [
                {
                    "name": "Airfare Price Index for India",
                    "dimensions": {
                        "series": [
                            {
                                "id": "FREQ",
                                "name": "Frequency",
                                "keyPosition": 0,
                                "values": [{"id": "M", "name": "Monthly"}],
                            },
                            {
                                "id": "ROUTE",
                                "name": "Route",
                                "keyPosition": 1,
                                "values": [{"id": "ALL", "name": "All basket routes"}]
                                + [{"id": r.code, "name": r.code} for r in basket.routes],
                            },
                            {
                                "id": "CARRIER_TYPE",
                                "name": "Carrier type",
                                "keyPosition": 2,
                                "values": [
                                    {"id": "ALL", "name": "All carriers"},
                                    {"id": "FSC", "name": "Full-service carrier"},
                                    {"id": "LCC", "name": "Low-cost carrier"},
                                    {"id": "REGIONAL", "name": "Regional"},
                                ],
                            },
                            {
                                "id": "AP_WINDOW",
                                "name": "Advance-purchase window",
                                "keyPosition": 3,
                                "values": [{"id": "ALL", "name": "All windows"}]
                                + [{"id": w.code, "name": w.label} for w in basket.advance_windows],
                            },
                        ],
                        "observation": [
                            {
                                "id": "TIME_PERIOD",
                                "name": "Time period",
                                "role": "time",
                                "values": time_period_values,
                            }
                        ],
                    },
                    "attributes": {
                        "series": [
                            {
                                "id": "UNIT_MEASURE",
                                "name": "Unit of measure",
                                "values": [{"id": "IX", "name": "Index, reference period = 100"}],
                            }
                        ],
                        "observation": [
                            {
                                "id": "OBS_STATUS",
                                "name": "Observation status",
                                "values": [
                                    {"id": "A", "name": "Normal"},
                                    {"id": "P", "name": "Provisional"},
                                ],
                            },
                            {
                                "id": "N_QUOTES",
                                "name": "Underlying cleaned quotes",
                                "values": n_quotes_values,
                            },
                        ],
                    },
                }
            ],
        },
    )
