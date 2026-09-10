"""The generated OpenAPI document must be genuinely valid OpenAPI 3.1 — not just
shaped like it. Needs no database: ``create_app().openapi()`` is pure introspection.
"""

from __future__ import annotations

from openapi_spec_validator import validate


def test_openapi_document_is_valid_openapi_3_1() -> None:
    from apix_api.main import create_app

    spec = create_app().openapi()
    assert spec["openapi"] == "3.1.0"
    validate(spec)
