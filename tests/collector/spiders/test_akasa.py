"""AkasaSpider: the JSON-endpoint-preferred, rendered-page-fallback contract."""

from __future__ import annotations

from datetime import date

import pytest

from apix_collector.spiders.akasa import AkasaSpider
from apix_collector.strategies.rendered_page import PlaywrightBrowserDriver
from apix_core.models.enums import CollectionMethod
from tests.collector.fakes import FakeBrowserDriver

TRAVEL_DATE = date(2026, 9, 18)
QUERY_DATE = date(2026, 8, 28)


def test_json_endpoint_succeeds_and_the_browser_is_never_touched(
    policy_engine, fixture_server
) -> None:
    driver = FakeBrowserDriver()  # no pages registered: any render() call would fail the test
    spider = AkasaSpider(
        fixture_base_url=f"{fixture_server.base_url}/airline_akasa",
        browser_driver=driver,
        policy_engine=policy_engine,
    )
    outcome = spider.collect(route_code="DEL-BOM", travel_date=TRAVEL_DATE, advance_days=21)
    assert outcome.strategy_name is CollectionMethod.PUBLIC_JSON_API
    assert len(outcome.quotes) == 1
    assert driver.requests == []


def test_missing_json_fixture_falls_back_to_the_rendered_page(
    policy_engine, fixture_server, repo_root
) -> None:
    """BOM-DEL has no recorded .json fixture — only the JsonEndpointStrategy sees a 404."""
    fallback_url = (
        f"{fixture_server.base_url}/airline_akasa/BOM-DEL.html"
        f"?travelDate={TRAVEL_DATE.isoformat()}&queryDate={QUERY_DATE.isoformat()}"
    )
    html = (repo_root / "fixtures" / "airline_akasa" / "BOM-DEL.html").read_text(encoding="utf-8")
    driver = FakeBrowserDriver(pages={fallback_url: html})
    spider = AkasaSpider(
        fixture_base_url=f"{fixture_server.base_url}/airline_akasa",
        browser_driver=driver,
        policy_engine=policy_engine,
    )
    outcome = spider.collect(route_code="BOM-DEL", travel_date=TRAVEL_DATE, advance_days=21)
    assert outcome.strategy_name is CollectionMethod.RENDERED_PAGE
    assert len(outcome.quotes) == 2
    assert driver.requests[0]["url"] == fallback_url


@pytest.mark.slow
def test_fallback_works_with_a_real_browser(policy_engine, fixture_server) -> None:
    """One end-to-end check with a real, installed Chromium — not part of the fast suite's
    default trust, which relies on FakeBrowserDriver, but real enough to catch a
    RenderedPageStrategy/PlaywrightBrowserDriver wiring bug the fake could not."""
    driver = PlaywrightBrowserDriver()
    try:
        spider = AkasaSpider(
            fixture_base_url=f"{fixture_server.base_url}/airline_akasa",
            browser_driver=driver,
            policy_engine=policy_engine,
        )
        outcome = spider.collect(route_code="BOM-DEL", travel_date=TRAVEL_DATE, advance_days=21)
        assert outcome.strategy_name is CollectionMethod.RENDERED_PAGE
        assert len(outcome.quotes) == 2
    finally:
        driver.close()
