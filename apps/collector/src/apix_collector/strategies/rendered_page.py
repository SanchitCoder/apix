"""Playwright fallback for JS-rendered results.

This strategy cannot go through ``PolicyEngine.request`` the way
:class:`~apix_collector.strategies.json_endpoint.JsonEndpointStrategy` does: a browser
makes its own network requests, not the policy engine's ``httpx`` client, and rendering
a page cannot be reduced to one HTTP call. It still never fetches without the policy
engine's say-so — it calls ``PolicyEngine.check`` first, which runs every gate (source,
robots, paths, rate limit) and records the decision, exactly as ``.request`` does
internally, before a single byte of the page is asked for.

Resource blocking (images, fonts, analytics beacons) is applied at the browser's
network layer so a full page render costs a fraction of the bandwidth a bare browser
would use.

Real Playwright driving lives in :class:`PlaywrightBrowserDriver`; everything else in
this module — including every test — is written against the :class:`BrowserDriver`
protocol, so unit tests never need a real, installed browser.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from apix_collector.errors import FetchFailed
from apix_collector.strategies.base import FetchedPayload, SimpleResponse
from apix_core.models.enums import CollectionMethod
from apix_core.policy import PolicyDenied

if TYPE_CHECKING:
    from playwright.sync_api import Browser as SyncBrowser

    from apix_collector.session import SessionContext
    from apix_core.policy import PolicyEngine

#: Playwright resource types worth refusing outright for a fare-search page: none of
#: them affect the priced itineraries the mapper reads out of the rendered DOM.
DEFAULT_BLOCKED_RESOURCE_TYPES: frozenset[str] = frozenset({"image", "font", "stylesheet", "media"})

#: Substrings matched against the request URL. Analytics/ad beacons cost bandwidth and
#: teach nothing about a fare.
DEFAULT_BLOCKED_HOST_SUBSTRINGS: frozenset[str] = frozenset(
    {
        "google-analytics.com",
        "googletagmanager.com",
        "doubleclick.net",
        "facebook.net",
        "hotjar.com",
        "segment.io",
        "clarity.ms",
    }
)


class BrowserNavigationError(RuntimeError):
    """The browser could not load the page (bad status, timeout, crash)."""


class BrowserDriver(Protocol):
    """Anything that can render a URL to HTML with resource blocking applied."""

    def render(
        self,
        url: str,
        *,
        block_resource_types: frozenset[str],
        block_host_substrings: frozenset[str],
    ) -> str:
        """Return the fully-rendered page HTML, or raise :class:`BrowserNavigationError`."""
        ...


@dataclass(slots=True)
class RenderedPageStrategy:
    """Renders ``url`` in a real browser after clearing it with the PolicyEngine."""

    driver: BrowserDriver
    block_resource_types: frozenset[str] = DEFAULT_BLOCKED_RESOURCE_TYPES
    block_host_substrings: frozenset[str] = DEFAULT_BLOCKED_HOST_SUBSTRINGS
    collection_method: CollectionMethod = CollectionMethod.RENDERED_PAGE

    @property
    def name(self) -> CollectionMethod:
        return self.collection_method

    def fetch(
        self,
        *,
        policy_engine: PolicyEngine,
        url: str,
        session: SessionContext,  # noqa: ARG002 — part of the AcquisitionStrategy contract;
        # a browser manages its own cookies/session, so there is nothing to attach this to.
    ) -> FetchedPayload:
        decision = policy_engine.check(url)
        if not decision.allowed:
            raise PolicyDenied(decision)
        try:
            html = self.driver.render(
                url,
                block_resource_types=self.block_resource_types,
                block_host_substrings=self.block_host_substrings,
            )
        except BrowserNavigationError as exc:
            raise FetchFailed(0, url, detail=str(exc)) from exc
        body = html.encode("utf-8")
        return FetchedPayload(
            body=body,
            response=SimpleResponse(url=url, content=body),
            collection_method=self.collection_method,
        )


class PlaywrightBrowserDriver:
    """Drives a real, headless Chromium instance — one per calling thread.

    Never imported by a unit test — ``make test`` exercises :class:`RenderedPageStrategy`
    against a fake :class:`BrowserDriver` so the suite never needs an installed browser.
    Used by ``apix_collector.run``/``apix_scheduler.flows.daily_sweep`` for a real
    ``make collect-once``/production run.

    Playwright's sync API is bound to the OS thread that started it — a browser handle
    created on one thread cannot be driven from another (``greenlet.error: Cannot
    switch to a different thread``). ``apix_scheduler.flows.daily_sweep`` submits tasks
    to Prefect's default thread-pool task runner, and a single ``PlaywrightBrowserDriver``
    is shared across every spider for the whole flow run, so ``render`` cannot assume it
    is always called from the thread that constructed this object: instead each thread
    lazily launches — and keeps — its own Playwright instance and browser the first time
    it calls :meth:`render`.

    ``close`` can only close the browser belonging to *its own* thread — Python cannot
    reach another thread's thread-local storage from the outside. Call it from every
    thread that rendered a page if you need a clean shutdown; otherwise the leftover
    browser processes exit with the process itself, which is the accepted cost for a
    batch flow that runs to completion and exits.
    """

    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._local: threading.local = threading.local()

    def _browser(self) -> SyncBrowser:
        browser: SyncBrowser | None = getattr(self._local, "browser", None)
        if browser is None:
            from playwright.sync_api import sync_playwright

            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=self._headless)
            self._local.playwright = playwright
            self._local.browser = browser
        return browser

    def render(
        self,
        url: str,
        *,
        block_resource_types: frozenset[str],
        block_host_substrings: frozenset[str],
    ) -> str:
        page = self._browser().new_page()

        def _maybe_block(route: object) -> None:
            request = route.request  # type: ignore[attr-defined]
            blocked = request.resource_type in block_resource_types or any(
                needle in request.url for needle in block_host_substrings
            )
            if blocked:
                route.abort()  # type: ignore[attr-defined]
            else:
                route.continue_()  # type: ignore[attr-defined]

        try:
            page.route("**/*", _maybe_block)
            response = page.goto(url, wait_until="networkidle")
            if response is None or not response.ok:
                status = response.status if response is not None else 0
                raise BrowserNavigationError(f"navigation to {url} failed (status={status})")
            return page.content()
        finally:
            page.close()

    def close(self) -> None:
        """Close this thread's browser and Playwright instance, if it created one."""
        browser: SyncBrowser | None = getattr(self._local, "browser", None)
        if browser is not None:
            browser.close()
            self._local.browser = None
        playwright = getattr(self._local, "playwright", None)
        if playwright is not None:
            playwright.stop()
            self._local.playwright = None


__all__ = [
    "DEFAULT_BLOCKED_HOST_SUBSTRINGS",
    "DEFAULT_BLOCKED_RESOURCE_TYPES",
    "BrowserDriver",
    "BrowserNavigationError",
    "PlaywrightBrowserDriver",
    "RenderedPageStrategy",
]
