from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apix_collector.errors import SchemaDriftError
from apix_collector.mappers.cleartrip import CleartripMapper
from apix_collector.quote import MapperContext

CONTEXT = MapperContext(
    route_code="DEL-BOM", travel_date=date(2026, 9, 18), query_date=date(2026, 8, 28)
)


def test_parses_the_recorded_fixture(repo_root) -> None:
    payload = (repo_root / "fixtures" / "ota_cleartrip" / "DEL-BOM.html").read_bytes()
    quotes = CleartripMapper().parse(payload, CONTEXT)
    assert len(quotes) == 2
    first = quotes[0]
    assert first.carrier_iata == "6E"
    assert first.flight_number == "6E2341"
    assert first.convenience_fee == Decimal("149.00")
    assert first.udf is None  # OTA markup does not break UDF out
    assert first.refundable is False
    assert quotes[1].refundable is True


def test_a_no_flights_page_returns_no_quotes_without_drifting() -> None:
    html = '<html><body><div class="noFlights">No flights found</div></body></html>'
    quotes = CleartripMapper().parse(html.encode("utf-8"), CONTEXT)
    assert quotes == []


def test_missing_attribute_triggers_drift(tmp_path) -> None:
    html = '<html><body><div class="fareCard" data-carrier="6E"></div></body></html>'
    mapper = CleartripMapper(drift_dir=tmp_path)
    with pytest.raises(SchemaDriftError):
        mapper.parse(html.encode("utf-8"), CONTEXT)
    assert any((tmp_path / "ota_cleartrip").glob("*"))


def test_non_utf8_body_triggers_drift(tmp_path) -> None:
    mapper = CleartripMapper(drift_dir=tmp_path)
    with pytest.raises(SchemaDriftError):
        mapper.parse(b"\xff\xfe not utf-8", CONTEXT)
