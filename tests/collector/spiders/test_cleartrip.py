"""CleartripSpider against the real fixture server, with a fake browser driver."""

from __future__ import annotations

from datetime import date

from apix_collector.spiders.cleartrip import CleartripSpider
from apix_core.models.enums import CollectionMethod
from tests.collector.fakes import FakeBrowserDriver


def test_collects_the_recorded_fixture_via_the_fake_driver(
    policy_engine, fixture_server, repo_root
) -> None:
    travel_date = date(2026, 9, 18)
    query_date = date(2026, 8, 28)
    fixture_url = (
        f"{fixture_server.base_url}/ota_cleartrip/DEL-BOM.html"
        f"?travelDate={travel_date.isoformat()}&queryDate={query_date.isoformat()}"
    )
    html = (repo_root / "fixtures" / "ota_cleartrip" / "DEL-BOM.html").read_text(encoding="utf-8")
    driver = FakeBrowserDriver(pages={fixture_url: html})

    spider = CleartripSpider(
        fixture_base_url=f"{fixture_server.base_url}/ota_cleartrip",
        browser_driver=driver,
        policy_engine=policy_engine,
    )
    outcome = spider.collect(route_code="DEL-BOM", travel_date=travel_date, advance_days=21)
    assert outcome.strategy_name is CollectionMethod.RENDERED_PAGE
    assert len(outcome.quotes) == 2
    (recorded,) = driver.requests
    assert recorded["url"] == fixture_url
