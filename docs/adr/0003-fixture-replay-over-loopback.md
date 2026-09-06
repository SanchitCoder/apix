# 3. Replay fixtures through a real PolicyEngine over a loopback HTTP server

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** APIx engineering
- **Touches:** `apix_collector.fixtureserver`, `apix_collector.run`, `config/sources.yaml`

## Context

Phase 2 needed to implement `apix_collector`: a `BaseSpider` contract, two acquisition
strategies, and three concrete spiders with recorded fixtures, runnable with no live
network access (`make collect-once`, `make test`).

At the same time, every real source in `config/sources.yaml` —
`airline_indigo`, `airline_akasa`, `ota_cleartrip` and the rest — is `enabled: false`
with `tos_verdict: NOT_REVIEWED`. `PolicyEngine` refuses to even construct around an
enabled-but-unreviewed source, and CLAUDE.md guardrail 3 is unconditional: no request
to an external source without going through `PolicyEngine.request` first. So the three
spiders had to be built, tested, and demonstrably wired to real compliance
machinery, while having **nothing they are currently allowed to fetch from**.

Two shapes were available for making that true without weakening the compliance model:

1. Bypass `PolicyEngine` for fixture-replay mode — have spiders read fixture bytes
   directly off disk when "replaying", and only call `PolicyEngine.request` in a
   separate, currently-dead "live" code path.
2. Give spiders exactly one thing they are legally allowed to reach, and make that
   thing real: an HTTP source, reviewed and enabled, that they fetch from through the
   real `PolicyEngine`, every time, whether under test or in `make collect-once`.

## Decision

**Option 2.** `config/sources.yaml` carries one enabled source, `fixture_replay` —
domain `localhost`, `legal_basis: FIXTURE`, restricted to `/fixtures/` — and
`apix_collector.fixtureserver.FixtureServer` serves this repository's `fixtures/`
directory over a real `http.server` bound to an OS-assigned loopback port. Every
spider's fixture-mode URL points there. `JsonEndpointStrategy` calls
`PolicyEngine.request` against it exactly as it would against a live JSON endpoint;
`RenderedPageStrategy` calls `PolicyEngine.check` (see below) and then drives a real,
installed Chromium at the same loopback URL.

Two consequences follow directly and are treated as correct, not as gaps:

- A `fare_quote` collected this way carries `collection_method=FIXTURE,
  legal_basis=FIXTURE`, decided by `apix_collector.run.run_spider_once`'s
  `fixture_mode` flag, regardless of which strategy actually served the request — that
  is what genuinely happened, whatever the mapper's long-run production behaviour
  would be once a source clears review.
- The quote's `source_id` still points at the semantic source (`airline_indigo`, not
  `fixture_replay`), because that is what the data represents; its authorising
  `policy_decision` was recorded against `fixture_replay`, not that source.
  `apix_core.provenance.resolve.resolve()` already anticipated exactly this split —
  its `ProvenanceChain.policy_decision` field is documented as `None` for
  "FIXTURE-legal-basis quotes replayed outside a live engine."

**`RenderedPageStrategy` cannot call `PolicyEngine.request`.** A browser makes its own
network requests; there is no single `httpx` call to hand to the policy engine, and
`apix_collector` is barred from importing an HTTP client outside
`apix_core.policy` (`tests/test_egress_only.py`) in any case. Instead it calls
`PolicyEngine.check`, which runs every gate (source, robots, paths, rate limit) and
records the decision — the same work `.request` does before it dials out — and only
then lets Playwright navigate. The audit trail is identical; only the transport that
performs the fetch differs.

## Consequences

**Good.**

- Nothing about the compliance model is special-cased for tests or for fixture mode.
  The exact same `PolicyEngine`, the exact same `JsonEndpointStrategy`/
  `RenderedPageStrategy`, and the exact same spiders run in `make test`,
  `make collect-once`, and (once a source clears review) production. There is no
  parallel "test-only" fetch path to keep in sync or to accidentally leave enabled.
- `tests/test_egress_only.py` and the no-live-internet rule both still hold literally:
  no module outside `apix_core.policy` imports an HTTP client, and no test reaches
  beyond the loopback interface of its own process.
- Rate limiting, robots handling and decision logging are exercised for real against a
  concurrent, multi-spider run, not mocked away — a regression in `PolicyEngine` that
  only shows up under real request timing has a chance of being caught by the
  collector's own tests.

**Costly.**

- `fixture_replay`'s own `tos_reviewed_at` is subject to the same 180-day staleness
  check as every real source, and unlike a real source there is no external counsel to
  re-review it — an APIx maintainer has to notice and bump the date periodically (see
  the comment above its entry in `config/sources.yaml`). Left unrenewed, `make
  collect-once` and the collector test suite both fail loudly with
  `PolicyStartupError`, which is the intended failure mode (loud, not silent) but does
  mean this file needs occasional, deliberate upkeep unrelated to any source going
  live.
- A `RenderedPageStrategy` test that wants to prove the real `PlaywrightBrowserDriver`
  works (not just the `BrowserDriver` protocol) needs an actually-installed Chromium.
  One such test exists (`tests/collector/spiders/test_akasa.py`, marked `slow`); every
  other rendered-page test runs against a fake driver so the default `make test` run
  stays fast and does not depend on a browser download succeeding.

**Deferred.**

- Once a source's ToS review lands and `config/sources.yaml` flips it to
  `enabled: true`, that spider's `fixture_base_url` needs to become a real live-URL
  builder (see the docstring on each spider in `apix_collector.spiders` for exactly
  what is deferred). This ADR's fixture-replay path does not go away — it stays the
  mechanism `make test` and fixture-based development use — but a live spider gains a
  second, real URL-building path alongside it.
