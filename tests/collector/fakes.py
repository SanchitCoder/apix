"""Test doubles shared across the collector suite."""

from __future__ import annotations

from dataclasses import dataclass, field

from apix_collector.strategies.rendered_page import BrowserNavigationError


@dataclass
class FakeBrowserDriver:
    """A :class:`~apix_collector.strategies.rendered_page.BrowserDriver` with no browser.

    ``pages`` maps a URL to the HTML it "renders" — set up by the test. A URL not in
    the map raises :class:`BrowserNavigationError`, exactly like a real 404/timeout
    would. Every call is recorded in ``requests`` so a test can assert resource
    blocking was requested (this fake does not actually filter anything — there is no
    real network layer to filter — it only proves the strategy asked for it).
    """

    pages: dict[str, str] = field(default_factory=dict)
    requests: list[dict[str, object]] = field(default_factory=list)

    def render(
        self,
        url: str,
        *,
        block_resource_types: frozenset[str],
        block_host_substrings: frozenset[str],
    ) -> str:
        self.requests.append(
            {
                "url": url,
                "block_resource_types": block_resource_types,
                "block_host_substrings": block_host_substrings,
            }
        )
        if url not in self.pages:
            raise BrowserNavigationError(f"no fake page registered for {url}")
        return self.pages[url]
