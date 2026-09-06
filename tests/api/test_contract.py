"""The API contract. These tests are what stops the front end being built on sand."""

from __future__ import annotations

import pytest

# Every endpoint in the contract, with a request that must succeed.
ENDPOINTS = [
    "/healthz",
    "/readyz",
    "/metrics",
    "/v1/index?series=APIX.ALL.M&freq=M",
    "/v1/index/vintage?series=APIX.ALL.M&period=2026-08-01&as_of=2026-09-01",
    "/v1/routes",
    "/v1/routes/DEL-BOM/series?advance_days=14",
    "/v1/leadtime/DEL-BOM",
    "/v1/heatmap?from=2026-04-01&to=2026-08-01",
    "/v1/decomposition?period=2026-08-01",
    "/v1/nowcast",
    "/v1/coverage?date=2026-09-01",
    "/v1/metadata/basket",
    "/v1/metadata/method",
    "/v1/provenance/00000000-0000-4000-8000-000000000003",
    "/v1/sdmx/data/IN_APIX,DF_AIRFARE_INDEX,1.0.0/M.ALL.ALL.ALL",
    "/v1/export.csv?series=APIX.ALL.M",
    "/v1/index/contributors?series=APIX.ALL.M&period=2026-08-01",
    "/v1/index/revisions?series=APIX.ALL.M",
    "/v1/quotes?route=DEL-BOM&period=2026-08-01",
    "/v1/routes/DEL-BOM/series?advance_days=3&carrier=6E",
    "/v1/leadtime/DEL-BOM?carrier=AI",
    "/v1/metadata/carriers",
]

PAGINATED = [
    "/v1/index",
    "/v1/routes",
    "/v1/routes/DEL-BOM/series",
    "/v1/heatmap",
    "/v1/nowcast",
    "/v1/index/contributors",
    "/v1/index/revisions",
    "/v1/quotes",
]


@pytest.mark.parametrize("path", ENDPOINTS)
def test_every_endpoint_answers(api_client, path: str) -> None:
    assert api_client.get(path).status_code == 200


@pytest.mark.parametrize("path", [p for p in ENDPOINTS if p.startswith("/v1")])
def test_v1_responses_are_labelled_as_examples(api_client, path: str) -> None:
    """Phase 1 serves placeholders. Nothing may look like a published statistic.

    When Phase 3 wires the database in, this test changes to assert the header reports
    the real status of the index run — it does not simply get deleted.
    """
    response = api_client.get(path)
    assert response.headers["X-APIx-Data-Status"] == "EXAMPLE_ONLY"


@pytest.mark.parametrize("path", PAGINATED)
def test_list_endpoints_are_paginated_with_a_cursor(api_client, path: str) -> None:
    body = api_client.get(path).json()
    assert set(body) == {"items", "pagination", "meta"}
    pagination = body["pagination"]
    assert pagination["returned"] == len(body["items"])
    assert isinstance(pagination["has_more"], bool)
    assert pagination["next_cursor"] is None or isinstance(pagination["next_cursor"], str)


def test_index_values_travel_with_their_evidence_base(api_client) -> None:
    """Principle 1: no number is served without what it rests on."""
    for point in api_client.get("/v1/index").json()["items"]:
        assert point["n_quotes"] >= 0
        assert "coverage_pct" in point
        assert "is_imputed" in point


def test_metadata_endpoints_serve_the_real_config(api_client) -> None:
    """These two are not placeholders: the basket and the method exist today."""
    basket = api_client.get("/v1/metadata/basket").json()
    assert basket["n_routes"] == 50
    assert basket["weights_populated"] is False
    assert all(r["dgca_pax_share"] is None for r in basket["routes"])

    method = api_client.get("/v1/metadata/method").json()
    assert len(method["config_hash"]) == 64
    assert method["elementary_formula"] == "jevons"


def test_provenance_resolves_a_quote_to_its_source_and_legal_basis(api_client) -> None:
    body = api_client.get("/v1/provenance/00000000-0000-4000-8000-000000000003").json()
    assert body["source"]["legal_basis"]
    assert body["source"]["policy_decision"] == "ALLOWED"
    assert body["contributed_to"]


def test_nowcast_carries_an_explicit_caveat(api_client) -> None:
    """A modelled estimate must not be mistakable for a published index value."""
    for point in api_client.get("/v1/nowcast").json()["items"]:
        assert "not a published index value" in point["caveat"]


def test_coverage_reports_gaps_rather_than_omitting_them(api_client) -> None:
    """Principle 2: an empty result is data."""
    body = api_client.get("/v1/coverage?date=2026-09-01").json()
    assert isinstance(body["routes_missing"], list)
    for source in body["sources"]:
        if source["status"] != "OK":
            assert source["reason"], f"{source['source_code']} is not OK but gives no reason"


def test_decomposition_reports_its_residual(api_client) -> None:
    body = api_client.get("/v1/decomposition?period=2026-08-01").json()
    assert "residual_pct_points" in body


def test_csv_export_carries_provenance_columns(api_client) -> None:
    response = api_client.get("/v1/export.csv?series=APIX.ALL.M")
    assert response.headers["content-type"].startswith("text/csv")
    header = response.text.splitlines()[0].split(",")
    assert "index_run_id" in header
    assert "data_status" in header


class TestMethodPreview:
    """The method console's contract: same settings, same series; changed settings, a
    visibly changed series; an unpublishable method, a 422 problem document."""

    def test_empty_overrides_preview_the_baseline(self, api_client) -> None:
        body = api_client.post("/v1/method/preview", json={}).json()
        assert body["is_baseline"] is True
        assert body["config_hash"] == body["baseline_config_hash"]
        for point in body["points"]:
            assert point["value"] == point["baseline_value"]

    def test_previews_are_deterministic(self, api_client) -> None:
        payload = {"elementary_formula": "dutot"}
        first = api_client.post("/v1/method/preview", json=payload).json()
        second = api_client.post("/v1/method/preview", json=payload).json()
        assert first["points"] == second["points"]
        assert first["config_hash"] == second["config_hash"]

    def test_a_changed_setting_changes_the_series(self, api_client) -> None:
        body = api_client.post(
            "/v1/method/preview", json={"multilateral_method": "geks_fisher"}
        ).json()
        assert body["is_baseline"] is False
        assert body["config_hash"] != body["baseline_config_hash"]
        assert any(p["value"] != p["baseline_value"] for p in body["points"])

    def test_preview_carries_its_diagnostics(self, api_client) -> None:
        body = api_client.post("/v1/method/preview", json={"imputation_rule": "none"}).json()
        diagnostics = body["diagnostics"]
        assert diagnostics["imputed_cell_count"] == 0
        assert {"coverage_pct", "outlier_dropped_count", "suppressed_cell_count"} <= set(
            diagnostics
        )

    def test_an_unpublishable_method_is_rejected(self, api_client) -> None:
        response = api_client.post("/v1/method/preview", json={"elementary_formula": "carli"})
        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/problem+json")

    def test_preview_is_labelled_as_example_data(self, api_client) -> None:
        response = api_client.post("/v1/method/preview", json={})
        assert response.headers["X-APIx-Data-Status"] == "EXAMPLE_ONLY"
        assert response.json()["meta"]["data_status"] == "EXAMPLE_ONLY"


def test_quotes_list_shows_treatments_not_only_survivors(api_client) -> None:
    """Principle 2: a dropped outlier and an imputed value are recorded as such."""
    items = api_client.get("/v1/quotes?route=DEL-BOM&period=2026-08-01").json()["items"]
    assert any(q["is_outlier"] and q["outlier_rule"] for q in items)
    assert any(q["is_imputed"] and q["imputation_method"] for q in items)


def test_contributors_report_absent_weights_as_null(api_client) -> None:
    """Unweighted means null, never an estimated share."""
    items = api_client.get("/v1/index/contributors?period=2026-08-01").json()["items"]
    assert items
    assert all(c["weight"] is None and c["contribution_pct_points"] is None for c in items)


def test_revision_log_includes_first_publications(api_client) -> None:
    items = api_client.get("/v1/index/revisions").json()["items"]
    assert any(e["old_value"] is None for e in items)
    assert all(e["reason"] for e in items)


def test_sdmx_message_has_the_2_0_envelope(api_client) -> None:
    body = api_client.get("/v1/sdmx/data/IN_APIX,DF_AIRFARE_INDEX,1.0.0/M.ALL.ALL.ALL").json()
    assert set(body) >= {"meta", "data"}
    assert body["data"]["dataSets"]
    assert body["data"]["structures"]


class TestErrors:
    def test_errors_are_rfc_9457_problem_documents(self, api_client) -> None:
        response = api_client.get("/v1/does-not-exist")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert set(body) >= {"type", "title", "status"}
        assert body["status"] == 404

    def test_validation_errors_are_problem_documents_too(self, api_client) -> None:
        response = api_client.get("/v1/leadtime/not-a-route-code")
        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["errors"]


class TestOpenApi:
    def test_document_is_openapi_3_1(self, api_client) -> None:
        assert api_client.get("/openapi.json").json()["openapi"] == "3.1.0"

    def test_every_contract_endpoint_is_documented(self, api_client) -> None:
        """The front end builds against this document; a missing path is a broken client."""
        paths = set(api_client.get("/openapi.json").json()["paths"])
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

    def test_from_is_exposed_under_its_documented_name(self, api_client) -> None:
        """`from` is a Python keyword; the parameter must still be named `from` on the wire."""
        params = api_client.get("/openapi.json").json()["paths"]["/v1/index"]["get"]["parameters"]
        assert "from" in {p["name"] for p in params}
