"""/v1/provenance/{quote_id} — the audit trail for a single observation."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from apix_api.errors import ERROR_RESPONSES
from apix_api.examples import EXAMPLE_CLEAN_ID, EXAMPLE_QUOTE_ID, response_meta
from apix_api.schemas import ProvenanceResponse, ProvenanceSource, ProvenanceTreatment

router = APIRouter(prefix="/v1", tags=["provenance"], responses=ERROR_RESPONSES)


@router.get(
    "/provenance/{quote_id}",
    summary="Full audit trail for one fare quote",
    response_model=ProvenanceResponse,
)
async def get_provenance(
    quote_id: Annotated[UUID, Path(description="fare_quote.id", examples=[EXAMPLE_QUOTE_ID])],
) -> ProvenanceResponse:
    """Resolve a quote back to its source, legal basis, cleaning and index contribution.

    This is principle 1 made operational. Every published index value is resolvable to
    the quotes behind it, and every quote is resolvable through this endpoint to the
    source it came from, the moment it was observed and the legal basis on which it was
    collected. If this endpoint cannot answer for a quote, that quote should not have
    contributed to a published number.
    """
    return ProvenanceResponse(
        quote_id=str(quote_id),
        collected_at="2026-08-15T06:30:00+00:00",
        run_id="00000000-0000-4000-8000-000000000005",
        route_code="DEL-BOM",
        carrier_iata="6E",
        travel_date=date(2026, 8, 29),
        query_date=date(2026, 8, 15),
        advance_days=14,
        total_fare=5000.00,
        currency="INR",
        source_url_hash="0" * 64,
        content_hash="1" * 64,
        raw_payload_ref="s3://apix-raw/2026/08/15/example.json.gz",
        source=ProvenanceSource(
            source_code="fixture_replay",
            display_name="Recorded fixture replay",
            domain="localhost",
            source_type="OFFICIAL",
            collection_method="FIXTURE",
            legal_basis="FIXTURE",
            policy_decision="ALLOWED",
            robots_fetched_at=None,
            tos_verdict="PERMITTED",
            tos_reviewed_at="2026-01-05T00:00:00+00:00",
        ),
        treatment=ProvenanceTreatment(
            clean_id=EXAMPLE_CLEAN_ID,
            is_outlier=False,
            outlier_rule=None,
            is_imputed=False,
            imputation_method=None,
            quality_vector={"completeness": 1.0, "source_agreement": 1.0, "staleness_h": 0},
        ),
        contributed_to=["APIX.ALL.M:2026-08", "APIX.ROUTE.DEL-BOM.M:2026-08"],
        meta=response_meta(method_version="2026.1", basket_version="2026.1"),
    )
