"""IndigoSpider against the real fixture server and a real PolicyEngine."""

from __future__ import annotations

from datetime import date

from apix_collector.spiders.indigo import IndigoSpider
from apix_core.models.enums import CollectionMethod


def test_collects_the_recorded_fixture(policy_engine, fixture_server) -> None:
    spider = IndigoSpider(
        fixture_base_url=f"{fixture_server.base_url}/airline_indigo",
        policy_engine=policy_engine,
    )
    outcome = spider.collect(route_code="DEL-BOM", travel_date=date(2026, 9, 18), advance_days=21)
    assert outcome.strategy_name is CollectionMethod.PUBLIC_JSON_API
    assert len(outcome.quotes) == 3
    assert outcome.route_code == "DEL-BOM"
    assert outcome.query_date == date(2026, 8, 28)
    assert "DEL-BOM.json" in str(outcome.payload.response.url)
