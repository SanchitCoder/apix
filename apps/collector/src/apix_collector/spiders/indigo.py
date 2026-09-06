"""IndiGo: airline's own site, internal JSON fare-search API only.

IndiGo's own booking flow calls a JSON endpoint to fill in search results, so this
spider declares a single strategy — there is no DOM to fall back to parsing because
none is needed.

``fixture_base_url`` currently points at this run's fixture-replay root
(``http://127.0.0.1:<port>/fixtures/airline_indigo``, see ``apix_collector.run`` and
``apix_collector.fixtureserver``), not IndiGo's real domain: ``config/sources.yaml``
lists ``airline_indigo`` as ``NOT_REVIEWED``/disabled, so live collection is not yet
legally cleared. A live URL builder (the real ``goindigo.in`` fare-search endpoint) is
future work for whoever completes that legal review — see CLAUDE.md guardrail 3.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, ClassVar

from apix_collector.mappers.indigo import IndigoMapper
from apix_collector.spiders.base import BaseSpider
from apix_collector.strategies.json_endpoint import JsonEndpointStrategy

if TYPE_CHECKING:
    from apix_collector.backoff import Backoff
    from apix_collector.budget import RunBudget
    from apix_collector.session import SessionRotator
    from apix_collector.strategies.base import AcquisitionStrategy
    from apix_core.policy import PolicyEngine


class IndigoSpider(BaseSpider):
    source_code: ClassVar[str] = "airline_indigo"

    def __init__(
        self,
        *,
        fixture_base_url: str,
        policy_engine: PolicyEngine,
        budget: RunBudget | None = None,
        max_requests_per_run: int = 20,
        retries: int = 2,
        session_rotator: SessionRotator | None = None,
        backoff: Backoff | None = None,
    ) -> None:
        super().__init__(
            mapper=IndigoMapper(),
            strategies=[JsonEndpointStrategy()],
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
        # Path is what the fixture server and the fixture_replay policy's
        # allowed_paths match on; the query string mirrors what a real fare-search
        # call would carry and is otherwise unused in replay.
        return (
            f"{self._fixture_base_url}/{route_code}.json"
            f"?travelDate={travel_date.isoformat()}&queryDate={query_date.isoformat()}"
        )


__all__ = ["IndigoSpider"]
