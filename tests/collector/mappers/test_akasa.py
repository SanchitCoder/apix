from __future__ import annotations

from datetime import date

import pytest

from apix_collector.errors import SchemaDriftError
from apix_collector.mappers.akasa import AkasaMapper
from apix_collector.quote import MapperContext

CONTEXT = MapperContext(
    route_code="DEL-BOM", travel_date=date(2026, 9, 18), query_date=date(2026, 8, 28)
)


def test_parses_the_json_endpoint_fixture(repo_root) -> None:
    payload = (repo_root / "fixtures" / "airline_akasa" / "DEL-BOM.json").read_bytes()
    quotes = AkasaMapper().parse(payload, CONTEXT)
    assert len(quotes) == 1
    quote = quotes[0]
    assert quote.carrier_iata == "QP"
    assert quote.flight_number == "QP1421"
    assert quote.total_fare == quote.base_fare + quote.taxes + quote.udf


def test_parses_the_rendered_page_fallback_fixture(repo_root) -> None:
    payload = (repo_root / "fixtures" / "airline_akasa" / "BOM-DEL.html").read_bytes()
    quotes = AkasaMapper().parse(payload, CONTEXT)
    assert len(quotes) == 2
    assert {q.fare_brand for q in quotes} == {"SAVER", "FLEXI"}


def test_neither_json_nor_embedded_script_is_drift(tmp_path) -> None:
    mapper = AkasaMapper(drift_dir=tmp_path)
    with pytest.raises(SchemaDriftError):
        mapper.parse(b"<html><body>nothing here</body></html>", CONTEXT)


def test_invalid_embedded_json_is_drift(tmp_path) -> None:
    mapper = AkasaMapper(drift_dir=tmp_path)
    payload = b"<script>window.__FARE_DATA__ = {not valid json};</script>"
    with pytest.raises(SchemaDriftError):
        mapper.parse(payload, CONTEXT)
