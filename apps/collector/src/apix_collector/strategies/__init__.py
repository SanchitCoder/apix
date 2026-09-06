"""Acquisition strategies: how a spider actually gets bytes off a source.

Two implementations, tried in the order a spider declares:

* :class:`~apix_collector.strategies.json_endpoint.JsonEndpointStrategy` — replays the
  internal JSON fare API a site's own front end calls. Preferred: faster, and far less
  brittle than DOM parsing.
* :class:`~apix_collector.strategies.rendered_page.RenderedPageStrategy` — a Playwright
  fallback for JS-rendered results, with resource blocking to cut bandwidth.

Both go through ``apix_core.policy.PolicyEngine`` before a single byte leaves the
process — see each module's docstring for exactly how, since a rendered page cannot
be fetched by the same HTTP client that the policy engine gates.
"""

from __future__ import annotations

from apix_collector.strategies.base import AcquisitionStrategy, FetchedPayload, SimpleResponse
from apix_collector.strategies.json_endpoint import JsonEndpointStrategy
from apix_collector.strategies.rendered_page import (
    BrowserDriver,
    BrowserNavigationError,
    PlaywrightBrowserDriver,
    RenderedPageStrategy,
)

__all__ = [
    "AcquisitionStrategy",
    "BrowserDriver",
    "BrowserNavigationError",
    "FetchedPayload",
    "JsonEndpointStrategy",
    "PlaywrightBrowserDriver",
    "RenderedPageStrategy",
    "SimpleResponse",
]
