"""/v1/sdmx — SDMX-JSON 2.0 endpoints.

SDMX is how a national statistics office consumes a series. MoSPI and the RBI ingest
SDMX; a bespoke JSON shape would need a bridge on their side, so the statistical
endpoints speak SDMX-JSON 2.0.0 natively.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Path, Response

from apix_api.errors import ERROR_RESPONSES
from apix_api.examples import EXAMPLE_PERIODS, EXAMPLE_VALUES
from apix_api.schemas import SdmxMessage

router = APIRouter(prefix="/v1/sdmx", tags=["sdmx"], responses=ERROR_RESPONSES)

SDMX_MEDIA_TYPE = "application/vnd.sdmx.data+json;version=2.0.0"

AGENCY_ID = "IN_APIX"
DATAFLOW_ID = "DF_AIRFARE_INDEX"
DATAFLOW_VERSION = "1.0.0"


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
                "Series key: dimension values in DSD order, dot-separated. `all` returns "
                "every series. Example `M.ALL.ALL.ALL` is FREQ.ROUTE.CARRIER_TYPE.AP_WINDOW."
            ),
            examples=["M.ALL.ALL.ALL"],
        ),
    ],
    response: Response = None,  # type: ignore[assignment]  # FastAPI injects the response
) -> SdmxMessage:
    """Serve one dataflow as an SDMX-JSON 2.0.0 data message.

    The observation attributes carry ``OBS_STATUS`` and the count of underlying quotes,
    so provenance survives the translation into SDMX rather than being dropped at the
    boundary.
    """
    if response is not None:
        response.headers["Content-Type"] = SDMX_MEDIA_TYPE

    observations = {str(i): [value, 0, 12_500] for i, value in enumerate(EXAMPLE_VALUES)}

    return SdmxMessage(
        meta={
            "schema": "https://raw.githubusercontent.com/sdmx-twg/sdmx-json/master/data-message/tools/schemas/2.0.0/sdmx-json-data-schema.json",
            "id": "APIX-EXAMPLE-MESSAGE",
            "prepared": datetime.now(tz=UTC).isoformat(),
            "test": True,
            "contentLanguages": ["en"],
            "sender": {"id": AGENCY_ID, "name": "APIx — Airfare Price Index for India"},
            # Non-standard but explicit: this message is a contract placeholder.
            "apix": {"dataStatus": "EXAMPLE_ONLY", "requestedFlowRef": flow_ref, "key": key},
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
                                "values": [{"id": "ALL", "name": "All basket routes"}],
                            },
                            {
                                "id": "CARRIER_TYPE",
                                "name": "Carrier type",
                                "keyPosition": 2,
                                "values": [{"id": "ALL", "name": "All carriers"}],
                            },
                            {
                                "id": "AP_WINDOW",
                                "name": "Advance-purchase window",
                                "keyPosition": 3,
                                "values": [{"id": "ALL", "name": "All windows"}],
                            },
                        ],
                        "observation": [
                            {
                                "id": "TIME_PERIOD",
                                "name": "Time period",
                                "role": "time",
                                "values": [
                                    {"id": p.strftime("%Y-%m"), "name": p.strftime("%Y-%m")}
                                    for p in EXAMPLE_PERIODS
                                ],
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
                                "values": [{"id": "A", "name": "Normal"}],
                            },
                            {
                                "id": "N_QUOTES",
                                "name": "Underlying cleaned quotes",
                                "values": [{"id": "12500", "name": "12500"}],
                            },
                        ],
                    },
                }
            ],
        },
    )
