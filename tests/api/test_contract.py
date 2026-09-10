"""The API contract. These tests are what stops the front end being built on sand.

Runs against the real, seeded database (see ``tests/api/conftest.py``) — the headline
series ``APIX.ALL.M`` is honestly unpublishable against the shipped basket (every
route's ``dgca_pax_share`` is null), so tests that need real, non-empty index data use
``ROUTE_SERIES`` (``APIX.ROUTE.DEL-BOM.M``) instead.
"""

from __future__ import annotations

import pytest

from tests.api.conftest import FIRST_AS_OF, ROUTE_SERIES
from tests.conftest import requires_docker

pytestmark = [pytest.mark.integration, requires_docker]

PERIOD = FIRST_AS_OF.replace(day=1).isoformat()

# Every public endpoint in the contract, with a request that must succeed.
PUBLIC_ENDPOINTS = [
    "/healthz",
    "/readyz",
    "/metrics",
    f"/v1/index?series={ROUTE_SERIES}&freq=M",
    f"/v1/index/vintage?series={ROUTE_SERIES}&period={PERIOD}&as_of=2026-09-01",
    "/v1/routes",
    "/v1/routes/DEL-BOM/series?advance_days=14",
    "/v1/leadtime/DEL-BOM",
    "/v1/heatmap",
    "/v1/coverage?date=2026-09-01",
    "/v1/metadata/basket",
    "/v1/metadata/method",
    "/v1/metadata/carriers",
    "/v1/sdmx/data/IN_APIX,DF_AIRFARE_INDEX,1.0.0/M.DEL-BOM.ALL.ALL",
    f"/v1/index/contributors?series={ROUTE_SERIES}&period={PERIOD}",
    f"/v1/index/revisions?series={ROUTE_SERIES}",
    "/v1/routes/DEL-BOM/series?advance_days=3&carrier=6E",
    "/v1/leadtime/DEL-BOM?carrier=AI",
]

# Microdata / draft-adjacent endpoints: require a researcher key.
MICRODATA_ENDPOINTS = [
    "/v1/provenance/{quote_id}",  # {quote_id} filled in by the test using a_real_quote_id
    f"/v1/export.csv?series={ROUTE_SERIES}",
    "/v1/quotes?route=DEL-BOM",
]

PAGINATED = [
    f"/v1/index?series={ROUTE_SERIES}",
    "/v1/routes",
    "/v1/routes/DEL-BOM/series",
    "/v1/heatmap",
    f"/v1/index/contributors?series={ROUTE_SERIES}&period={PERIOD}",
    f"/v1/index/revisions?series={ROUTE_SERIES}",
    "/v1/quotes?route=DEL-BOM",
]


@pytest.mark.parametrize("path", PUBLIC_ENDPOINTS)
async def test_every_public_endpoint_answers(api_async_client, path: str) -> None:
    response = await api_async_client.get(path)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("path", [p for p in MICRODATA_ENDPOINTS if "{quote_id}" not in p])
async def test_microdata_endpoints_require_a_key(api_async_client, path: str) -> None:
    assert (await api_async_client.get(path)).status_code == 403


@pytest.mark.parametrize("path", [p for p in MICRODATA_ENDPOINTS if "{quote_id}" not in p])
async def test_microdata_endpoints_answer_with_a_key(
    api_async_client, researcher_headers, path: str
) -> None:
    response = await api_async_client.get(path, headers=researcher_headers)
    assert response.status_code == 200, response.text


async def test_provenance_requires_a_key(api_async_client, a_real_quote_id) -> None:
    response = await api_async_client.get(f"/v1/provenance/{a_real_quote_id}")
    assert response.status_code == 403


@pytest.mark.parametrize("path", [p for p in PUBLIC_ENDPOINTS if p.startswith("/v1")])
async def test_v1_responses_report_real_data_status(api_async_client, path: str) -> None:
    """Every /v1 response is backed by real data now: the header reports the real
    status of the underlying index run, never the Phase-1 EXAMPLE_ONLY placeholder.
    """
    response = await api_async_client.get(path)
    assert response.headers["X-APIx-Data-Status"] in {"PUBLISHED", "PROVISIONAL"}


@pytest.mark.parametrize("path", PAGINATED)
async def test_list_endpoints_are_paginated_with_a_cursor(api_async_client, path: str) -> None:
    body = (await api_async_client.get(path)).json()
    assert set(body) == {"items", "pagination", "meta"}
    pagination = body["pagination"]
    assert pagination["returned"] == len(body["items"])
    assert isinstance(pagination["has_more"], bool)
    assert pagination["next_cursor"] is None or isinstance(pagination["next_cursor"], str)


async def test_index_values_travel_with_their_evidence_base(api_async_client) -> None:
    """Principle 1: no number is served without what it rests on."""
    body = await api_async_client.get(f"/v1/index?series={ROUTE_SERIES}")
    items = body.json()["items"]
    assert items
    for point in items:
        assert point["n_quotes"] >= 0
        assert "coverage_pct" in point
        assert "is_imputed" in point


async def test_metadata_endpoints_serve_the_real_config(api_async_client) -> None:
    """These are not placeholders: the basket and the method exist today."""
    basket = (await api_async_client.get("/v1/metadata/basket")).json()
    assert basket["n_routes"] == 50
    assert basket["weights_populated"] is False
    assert all(r["dgca_pax_share"] is None for r in basket["routes"])

    method = (await api_async_client.get("/v1/metadata/method")).json()
    assert len(method["config_hash"]) == 64
    assert method["elementary_formula"] == "jevons"

    carriers = (await api_async_client.get("/v1/metadata/carriers")).json()
    assert carriers["carriers"]


async def test_provenance_resolves_a_quote_to_its_source_and_legal_basis(
    api_async_client, researcher_headers, a_real_quote_id
) -> None:
    body = (
        await api_async_client.get(f"/v1/provenance/{a_real_quote_id}", headers=researcher_headers)
    ).json()
    assert body["source"]["legal_basis"]
    assert body["contributed_to"]


async def test_decomposition_is_an_honest_503(api_async_client) -> None:
    """No decomposition methodology is implemented — CLAUDE.md principle 5: raise
    rather than fabricate a mix_route/mix_carrier breakdown.
    """
    response = await api_async_client.get(f"/v1/decomposition?period={PERIOD}")
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_nowcast_is_an_honest_503(api_async_client) -> None:
    """apix_core.nowcast is an empty stub — same principle."""
    response = await api_async_client.get("/v1/nowcast")
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_coverage_reports_gaps_rather_than_omitting_them(api_async_client) -> None:
    """Principle 2: an empty result is data."""
    body = (await api_async_client.get("/v1/coverage?date=2026-09-01")).json()
    assert isinstance(body["routes_missing"], list)
    for source in body["sources"]:
        if source["status"] != "OK":
            assert source["reason"], f"{source['source_code']} is not OK but gives no reason"


async def test_csv_export_carries_provenance_columns(api_async_client, researcher_headers) -> None:
    response = await api_async_client.get(
        f"/v1/export.csv?series={ROUTE_SERIES}", headers=researcher_headers
    )
    assert response.headers["content-type"].startswith("text/csv")
    header = response.text.splitlines()[0].split(",")
    assert "index_run_id" in header
    assert "data_status" in header


class TestMethodPreview:
    """The method console's contract: same settings, same computed value; changed
    settings, a visibly changed value; an unpublishable method, a 422 problem document.
    """

    async def test_empty_overrides_preview_the_baseline(
        self, api_async_client, researcher_headers
    ) -> None:
        body = (
            await api_async_client.post("/v1/method/preview", json={}, headers=researcher_headers)
        ).json()
        assert body["is_baseline"] is True
        assert body["config_hash"] == body["baseline_config_hash"]
        for point in body["points"]:
            assert point["value"] == point["baseline_value"]

    async def test_previews_are_deterministic(self, api_async_client, researcher_headers) -> None:
        payload = {"elementary_formula": "dutot"}
        first = (
            await api_async_client.post(
                "/v1/method/preview", json=payload, headers=researcher_headers
            )
        ).json()
        second = (
            await api_async_client.post(
                "/v1/method/preview", json=payload, headers=researcher_headers
            )
        ).json()
        assert first["points"] == second["points"]
        assert first["config_hash"] == second["config_hash"]

    async def test_an_unpublishable_method_is_rejected(
        self, api_async_client, researcher_headers
    ) -> None:
        response = await api_async_client.post(
            "/v1/method/preview",
            json={"elementary_formula": "carli"},
            headers=researcher_headers,
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/problem+json")

    async def test_preview_is_never_labelled_as_published(
        self, api_async_client, researcher_headers
    ) -> None:
        response = await api_async_client.post(
            "/v1/method/preview", json={}, headers=researcher_headers
        )
        assert response.headers["X-APIx-Data-Status"] == "PREVIEW"
        assert response.json()["meta"]["data_status"] == "PREVIEW"

    async def test_preview_requires_a_key(self, api_async_client) -> None:
        response = await api_async_client.post("/v1/method/preview", json={})
        assert response.status_code == 403


async def test_quotes_list_shows_treatments_not_only_survivors(
    api_async_client, researcher_headers
) -> None:
    """Principle 2: a dropped outlier and an imputed value are recorded as such."""
    items = (
        await api_async_client.get(
            f"/v1/quotes?route=DEL-BOM&period={PERIOD}", headers=researcher_headers
        )
    ).json()["items"]
    assert items


async def test_contributors_report_absent_weights_as_null(api_async_client) -> None:
    """Unweighted means null, never an estimated share."""
    items = (await api_async_client.get(f"/v1/index/contributors?period={PERIOD}")).json()["items"]
    assert items
    assert all(c["weight"] is None and c["contribution_pct_points"] is None for c in items)


async def test_revision_log_includes_first_publications(api_async_client) -> None:
    items = (await api_async_client.get(f"/v1/index/revisions?series={ROUTE_SERIES}")).json()[
        "items"
    ]
    assert items
    assert any(e["old_value"] is None for e in items)
    assert all(e["reason"] for e in items)


async def test_sdmx_message_has_the_2_0_envelope(api_async_client) -> None:
    body = (
        await api_async_client.get("/v1/sdmx/data/IN_APIX,DF_AIRFARE_INDEX,1.0.0/M.DEL-BOM.ALL.ALL")
    ).json()
    assert set(body) >= {"meta", "data"}
    assert body["data"]["dataSets"]
    assert body["data"]["structures"]


class TestErrors:
    async def test_errors_are_rfc_9457_problem_documents(self, api_async_client) -> None:
        response = await api_async_client.get("/v1/does-not-exist")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert set(body) >= {"type", "title", "status"}
        assert body["status"] == 404

    async def test_validation_errors_are_problem_documents_too(self, api_async_client) -> None:
        response = await api_async_client.get("/v1/leadtime/not-a-route-code")
        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["errors"]


class TestOpenApi:
    async def test_document_is_openapi_3_1(self, api_async_client) -> None:
        assert (await api_async_client.get("/openapi.json")).json()["openapi"] == "3.1.0"

    async def test_every_contract_endpoint_is_documented(self, api_async_client) -> None:
        """The front end builds against this document; a missing path is a broken client."""
        paths = set((await api_async_client.get("/openapi.json")).json()["paths"])
        expected = {
            "/healthz",
            "/readyz",
            "/metrics",
            "/v1/index",
            "/v1/index/vintage",
            "/v1/routes",
            "/v1/routes/{code}/series",
            "/v1/leadtime/{code}",
            "/v1/heatmap",
            "/v1/decomposition",
            "/v1/nowcast",
            "/v1/coverage",
            "/v1/metadata/basket",
            "/v1/metadata/method",
            "/v1/provenance/{quote_id}",
            "/v1/sdmx/data/{flow_ref}/{key}",
            "/v1/export.csv",
            "/v1/index/contributors",
            "/v1/index/revisions",
            "/v1/quotes",
            "/v1/method/preview",
            "/v1/metadata/carriers",
        }
        assert expected <= paths

    async def test_from_is_exposed_under_its_documented_name(self, api_async_client) -> None:
        """`from` is a Python keyword; the parameter must still be named `from` on the wire."""
        doc = (await api_async_client.get("/openapi.json")).json()
        params = doc["paths"]["/v1/index"]["get"]["parameters"]
        assert "from" in {p["name"] for p in params}
