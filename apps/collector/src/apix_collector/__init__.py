"""APIx collectors.

Three spiders (``apix_collector.spiders``), two acquisition strategies
(``apix_collector.strategies``: an internal JSON endpoint, preferred, and a Playwright
rendered-page fallback), one mapper per source (``apix_collector.mappers``) turning a
source's response shape into ``apix_collector.quote.RawQuote``, and
``apix_collector.run``/``apix_collector.cli`` wiring a spider's outcome into
``collection_run``/``fare_quote`` rows with full provenance.

Two constraints bind everything in this package:

* No spider issues an HTTP request directly. Every fetch goes through
  ``apix_core.policy.PolicyEngine.request`` (or, for a rendered page a policy-engine
  ``httpx`` client cannot drive, ``PolicyEngine.check`` before the browser navigates)
  which decides, records the decision and only then lets the fetch happen.
* No test in this package touches the live internet. Every real source in
  ``config/sources.yaml`` is still ``NOT_REVIEWED``/disabled pending legal review, so
  every spider today only ever legally reaches the one enabled, ``FIXTURE``-basis
  source: recorded responses replayed from ``fixtures/`` over a loopback-only HTTP
  server (``apix_collector.fixtureserver``) that never leaves the machine.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
