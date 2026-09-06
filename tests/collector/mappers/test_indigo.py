from __future__ import annotations

import json
from datetime import date

import pytest

from apix_collector.errors import SchemaDriftError
from apix_collector.mappers.indigo import IndigoMapper
from apix_collector.quote import MapperContext

CONTEXT = MapperContext(
    route_code="DEL-BOM", travel_date=date(2026, 9, 18), query_date=date(2026, 8, 28)
)


@pytest.fixture
def fixture_payload(repo_root) -> bytes:
    return (repo_root / "fixtures" / "airline_indigo" / "DEL-BOM.json").read_bytes()


def test_parses_the_recorded_fixture(fixture_payload: bytes) -> None:
    mapper = IndigoMapper()
    quotes = mapper.parse(fixture_payload, CONTEXT)
    assert len(quotes) == 3  # two fare options on the first flight, one on the second
    first = quotes[0]
    assert first.carrier_iata == "6E"
    assert first.flight_number == "6E2341"
    assert first.fare_brand == "SAVER"
    assert first.total_fare == first.base_fare + first.taxes + first.udf
    assert first.convenience_fee is None
    assert first.currency == "INR"
    assert first.refundable is False


def test_invalid_json_triggers_drift(tmp_path) -> None:
    mapper = IndigoMapper(drift_dir=tmp_path)
    with pytest.raises(SchemaDriftError):
        mapper.parse(b"not json at all", CONTEXT)
    assert any(tmp_path.rglob("*"))


def test_missing_required_field_triggers_drift(tmp_path) -> None:
    mapper = IndigoMapper(drift_dir=tmp_path)
    payload = json.dumps({"itineraries": [{"flightNumber": "6E1"}]}).encode("utf-8")
    with pytest.raises(SchemaDriftError) as excinfo:
        mapper.parse(payload, CONTEXT)
    assert excinfo.value.source_code == "airline_indigo"
    captured = list((tmp_path / "airline_indigo").glob("*.json"))
    assert len(captured) == 1
    assert json.loads(captured[0].read_bytes()) == {"itineraries": [{"flightNumber": "6E1"}]}


def test_top_level_shape_change_triggers_drift(tmp_path) -> None:
    mapper = IndigoMapper(drift_dir=tmp_path)
    payload = json.dumps({"results": []}).encode("utf-8")  # renamed "itineraries"
    with pytest.raises(SchemaDriftError):
        mapper.parse(payload, CONTEXT)
