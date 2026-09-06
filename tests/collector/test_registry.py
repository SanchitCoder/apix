from __future__ import annotations

from apix_collector.registry import SOURCE_CODES, build_spiders
from tests.collector.fakes import FakeBrowserDriver


def test_source_codes_match_the_three_required_spiders() -> None:
    assert SOURCE_CODES == ("airline_indigo", "airline_akasa", "ota_cleartrip")


def test_build_spiders_wires_each_source_under_its_own_subtree(policy_engine) -> None:
    spiders = build_spiders(
        fixture_root_url="http://localhost:1/fixtures",
        policy_engine=policy_engine,
        browser_driver=FakeBrowserDriver(),
    )
    assert [s.source_code for s in spiders] == list(SOURCE_CODES)
