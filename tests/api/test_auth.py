"""Role resolution and the microdata/draft-data gate, against the real auth/rate-limit
choke point (``apix_api.middleware.enforce_access_control``).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apix_core.models import ApiKey, Role
from apix_core.provenance.hashing import sha256_hex
from tests.api.conftest import ROUTE_SERIES
from tests.conftest import requires_docker

pytestmark = [pytest.mark.integration, requires_docker]

MICRODATA_PATH = "/v1/quotes"


async def test_public_caller_is_rejected_from_microdata(api_async_client) -> None:
    response = await api_async_client.get(MICRODATA_PATH, params={"route": "DEL-BOM"})
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_researcher_key_is_admitted_to_microdata(
    api_async_client, researcher_headers
) -> None:
    response = await api_async_client.get(
        MICRODATA_PATH, params={"route": "DEL-BOM"}, headers=researcher_headers
    )
    assert response.status_code == 200


async def test_unknown_api_key_is_rejected(api_async_client) -> None:
    response = await api_async_client.get(
        MICRODATA_PATH, params={"route": "DEL-BOM"}, headers={"X-API-Key": "not-a-real-key"}
    )
    assert response.status_code == 401


async def test_revoked_api_key_is_rejected(api_async_client, seeded_database_url) -> None:
    plaintext = "revoked-test-key"
    engine = create_engine(seeded_database_url)
    try:
        with Session(engine) as session:
            from datetime import UTC, datetime

            session.add(
                ApiKey(
                    id=uuid.uuid4(),
                    key_hash=sha256_hex(plaintext.encode("utf-8")),
                    role=Role.RESEARCHER,
                    label="revoked fixture",
                    revoked_at=datetime.now(tz=UTC),
                )
            )
            session.commit()
    finally:
        engine.dispose()

    response = await api_async_client.get(
        MICRODATA_PATH, params={"route": "DEL-BOM"}, headers={"X-API-Key": plaintext}
    )
    assert response.status_code == 401


async def test_public_reads_a_published_series_without_any_key(api_async_client) -> None:
    """Published series stay open: the gate is on microdata/drafts, not on reading."""
    response = await api_async_client.get("/v1/index", params={"series": ROUTE_SERIES})
    assert response.status_code == 200
