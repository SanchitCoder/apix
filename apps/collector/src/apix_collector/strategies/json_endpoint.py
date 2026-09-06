"""Replay a source's internal JSON fare API.

Most travel sites' own front ends call an internal JSON endpoint to fill in search
results. Hitting that endpoint directly is the preferred acquisition strategy: it is
faster than rendering a page and, because it is a stable data contract rather than a
DOM structure, far less brittle to redesigns — a mapper only has to survive the API
changing, not the CSS changing too.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from apix_collector.errors import FetchFailed
from apix_collector.strategies.base import FetchedPayload
from apix_core.models.enums import CollectionMethod

if TYPE_CHECKING:
    from apix_collector.session import SessionContext
    from apix_core.policy import PolicyEngine


@dataclass(slots=True)
class JsonEndpointStrategy:
    """Fetches ``url`` through the PolicyEngine and expects a JSON body back.

    ``collection_method`` defaults to ``PUBLIC_JSON_API`` — the honest description of
    what this strategy does against a live source — but ``apix_collector.run`` passes
    ``FIXTURE`` when the whole run is a recorded-fixture replay, since that is what
    actually happened regardless of which strategy served it.
    """

    collection_method: CollectionMethod = CollectionMethod.PUBLIC_JSON_API

    @property
    def name(self) -> CollectionMethod:
        return self.collection_method

    def fetch(
        self, *, policy_engine: PolicyEngine, url: str, session: SessionContext
    ) -> FetchedPayload:
        response = policy_engine.request(url, headers=dict(session.headers))
        if response.status_code >= 400:
            raise FetchFailed(response.status_code, url)
        return FetchedPayload(
            body=response.content, response=response, collection_method=self.collection_method
        )


__all__ = ["JsonEndpointStrategy"]
