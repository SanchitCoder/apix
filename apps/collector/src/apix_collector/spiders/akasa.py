"""Akasa Air: internal JSON fare API preferred, rendered page as fallback.

Demonstrates the strategy-fallback contract: :class:`JsonEndpointStrategy` is tried
first, and only if it fails outright (a non-retryable status, or retries exhausted on
a retryable one) does the spider fall back to
:class:`~apix_collector.strategies.rendered_page.RenderedPageStrategy`.

``fixture_base_url`` is this run's fixture-replay root, not Akasa's real domain — see
``apix_collector.spiders.indigo`` for why (``config/sources.yaml`` still lists
``airline_akasa`` as ``NOT_REVIEWED``).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, ClassVar

from apix_collector.mappers.akasa import AkasaMapper
from apix_collector.spiders.base import BaseSpider
from apix_collector.strategies.json_endpoint import JsonEndpointStrategy
from apix_collector.strategies.rendered_page import RenderedPageStrategy

if TYPE_CHECKING:
    from apix_collector.backoff import Backoff
    from apix_collector.budget import RunBudget
    from apix_collector.session import SessionRotator
    from apix_collector.strategies.base import AcquisitionStrategy
    from apix_collector.strategies.rendered_page import BrowserDriver
    from apix_core.policy import PolicyEngine


class AkasaSpider(BaseSpider):
    source_code: ClassVar[str] = "airline_akasa"

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
            mapper=AkasaMapper(),
            strategies=[JsonEndpointStrategy(), RenderedPageStrategy(driver=browser_driver)],
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
        strategy: AcquisitionStrategy,
        *,
        route_code: str,
        travel_date: date,
        query_date: date,
    ) -> str:
        extension = "json" if isinstance(strategy, JsonEndpointStrategy) else "html"
        return (
            f"{self._fixture_base_url}/{route_code}.{extension}"
            f"?travelDate={travel_date.isoformat()}&queryDate={query_date.isoformat()}"
        )


__all__ = ["AkasaSpider"]
