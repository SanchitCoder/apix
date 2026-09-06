from __future__ import annotations

import pytest

from apix_collector.errors import FetchFailed
from apix_collector.session import SessionRotator
from apix_collector.strategies.rendered_page import (
    DEFAULT_BLOCKED_HOST_SUBSTRINGS,
    DEFAULT_BLOCKED_RESOURCE_TYPES,
    RenderedPageStrategy,
)
from apix_core.models.enums import CollectionMethod
from apix_core.policy import PolicyDenied
from tests.collector.fakes import FakeBrowserDriver


def test_renders_via_the_fake_driver_after_a_real_policy_check(policy_engine) -> None:
    fixture_url = "http://localhost/fixtures/ota_cleartrip/DEL-BOM.html"
    driver = FakeBrowserDriver(pages={fixture_url: "<html>ok</html>"})
    strategy = RenderedPageStrategy(driver=driver)
    payload = strategy.fetch(
        policy_engine=policy_engine,
        url="http://localhost/fixtures/ota_cleartrip/DEL-BOM.html",
        session=SessionRotator().next(),
    )
    assert payload.collection_method is CollectionMethod.RENDERED_PAGE
    assert payload.body == b"<html>ok</html>"
    assert payload.response.url == "http://localhost/fixtures/ota_cleartrip/DEL-BOM.html"
    (recorded,) = driver.requests
    assert recorded["block_resource_types"] == DEFAULT_BLOCKED_RESOURCE_TYPES
    assert recorded["block_host_substrings"] == DEFAULT_BLOCKED_HOST_SUBSTRINGS


def test_denied_url_never_reaches_the_driver(policy_engine) -> None:
    driver = FakeBrowserDriver()
    strategy = RenderedPageStrategy(driver=driver)
    with pytest.raises(PolicyDenied):
        strategy.fetch(
            policy_engine=policy_engine,
            url="https://www.cleartrip.com/flights/results",
            session=SessionRotator().next(),
        )
    assert driver.requests == []


def test_navigation_failure_becomes_fetch_failed(policy_engine) -> None:
    driver = FakeBrowserDriver()  # no pages registered: every render() raises
    strategy = RenderedPageStrategy(driver=driver)
    with pytest.raises(FetchFailed) as excinfo:
        strategy.fetch(
            policy_engine=policy_engine,
            url="http://localhost/fixtures/ota_cleartrip/DEL-BOM.html",
            session=SessionRotator().next(),
        )
    assert excinfo.value.status_code == 0
