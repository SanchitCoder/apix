"""The set of spiders this collector runs, and how to wire them for fixture replay.

One place both ``apix_collector.cli`` (``make collect-once``) and
``apix_scheduler.flows.daily_sweep`` build the same three spiders from, so the two
never drift apart on which sources exist or how their fixture URLs are constructed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from apix_collector.spiders.akasa import AkasaSpider
from apix_collector.spiders.cleartrip import CleartripSpider
from apix_collector.spiders.indigo import IndigoSpider

if TYPE_CHECKING:
    from apix_collector.spiders.base import BaseSpider
    from apix_collector.strategies.rendered_page import BrowserDriver
    from apix_core.policy import PolicyEngine

#: Every source this collector implements, keyed by ``source.code``.
SOURCE_CODES: tuple[str, ...] = (
    IndigoSpider.source_code,
    AkasaSpider.source_code,
    CleartripSpider.source_code,
)


def build_spiders(
    *,
    fixture_root_url: str,
    policy_engine: PolicyEngine,
    browser_driver: BrowserDriver,
) -> list[BaseSpider]:
    """Every spider, each pointed at its own subtree of ``fixture_root_url``.

    ``fixture_root_url`` is the ``fixture_replay`` source's ``/fixtures`` root (see
    ``apix_collector.fixtureserver.FixtureServer.base_url``) — every real source is
    still ``NOT_REVIEWED``/disabled in ``config/sources.yaml``, so this is the only
    thing any spider can legally reach today.
    """
    return [
        IndigoSpider(
            fixture_base_url=f"{fixture_root_url}/{IndigoSpider.source_code}",
            policy_engine=policy_engine,
        ),
        AkasaSpider(
            fixture_base_url=f"{fixture_root_url}/{AkasaSpider.source_code}",
            browser_driver=browser_driver,
            policy_engine=policy_engine,
        ),
        CleartripSpider(
            fixture_base_url=f"{fixture_root_url}/{CleartripSpider.source_code}",
            browser_driver=browser_driver,
            policy_engine=policy_engine,
        ),
    ]


__all__ = ["SOURCE_CODES", "build_spiders"]
