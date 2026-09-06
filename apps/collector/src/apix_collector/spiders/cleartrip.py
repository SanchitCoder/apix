"""Cleartrip: OTA aggregator, rendered results page only.

An aggregator's search results are assembled client-side from several supplier calls;
there is no single internal JSON endpoint worth replaying, so this spider declares
only :class:`~apix_collector.strategies.rendered_page.RenderedPageStrategy`.

``fixture_base_url`` is this run's fixture-replay root, not Cleartrip's real domain —
see ``apix_collector.spiders.indigo`` for why (``config/sources.yaml`` still lists
``ota_cleartrip`` as ``NOT_REVIEWED``).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, ClassVar

from apix_collector.mappers.cleartrip import CleartripMapper
from apix_collector.spiders.base import BaseSpider
from apix_collector.strategies.rendered_page import RenderedPageStrategy

if TYPE_CHECKING:
    from apix_collector.backoff import Backoff
    from apix_collector.budget import RunBudget
    from apix_collector.session import SessionRotator
    from apix_collector.strategies.base import AcquisitionStrategy
    from apix_collector.strategies.rendered_page import BrowserDriver
    from apix_core.policy import PolicyEngine


class CleartripSpider(BaseSpider):
    source_code: ClassVar[str] = "ota_cleartrip"

    def __init__(
        self,
        *,
        fixture_base_url: str,
        browser_driver: BrowserDriver,
        policy_engine: PolicyEngine,
        budget: RunBudget | None = None,
        max_requests_per_run: int = 20,
        retries: int = 2,
        session_rotator: SessionRotator | None = None,
        backoff: Backoff | None = None,
    ) -> None:
        super().__init__(
            mapper=CleartripMapper(),
            strategies=[RenderedPageStrategy(driver=browser_driver)],
            policy_engine=policy_engine,
            budget=budget,
            max_requests_per_run=max_requests_per_run,
            retries=retries,
            session_rotator=session_rotator,
            backoff=backoff,
        )
        self._fixture_base_url = fixture_base_url.rstrip("/")

    def build_url(
        self,
        _strategy: AcquisitionStrategy,
        *,
        route_code: str,
        travel_date: date,
        query_date: date,
    ) -> str:
        return (
            f"{self._fixture_base_url}/{route_code}.html"
            f"?travelDate={travel_date.isoformat()}&queryDate={query_date.isoformat()}"
        )


__all__ = ["CleartripSpider"]
