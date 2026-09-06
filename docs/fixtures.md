# Recording and replaying collector fixtures

How `fixtures/airline_indigo/`, `fixtures/airline_akasa/` and `fixtures/ota_cleartrip/`
came to exist, how they are replayed, and the procedure for adding or refreshing one.
Anything not recorded this way is not a fixture APIx will trust — principle 1 in
`CLAUDE.md` applies to test data too: a fixture with no recorded provenance is not
distinguishable from an invented one.

## Why fixtures instead of live collection

Every real source in `config/sources.yaml` — `airline_indigo`, `airline_akasa`,
`ota_cleartrip` and the rest — ships `enabled: false` with `tos_verdict:
NOT_REVIEWED`. `PolicyEngine` refuses to start at all if an enabled source is not
`PERMITTED` (`apix_core.policy.engine.PolicyEngine._validate_startup`), so **no code
in this repository can legally fetch from any of them yet**. That is a compliance
decision, not a temporary gap to route around: automated collection stays off until
counsel has reviewed each source's terms and recorded a verdict and a date.

Until that happens, the only thing a spider can legally reach is `fixture_replay` —
the one source in `config/sources.yaml` that is enabled, with `legal_basis: FIXTURE`,
restricted to paths under `/fixtures/`. `apix_collector.fixtureserver.FixtureServer`
serves this repository's `fixtures/` directory over a loopback-only HTTP server (no
packet ever reaches an external host), and every spider still goes through the real
`PolicyEngine` to reach it — `apix_collector.run.run_spider_once` then tags the
resulting `fare_quote` rows `collection_method=FIXTURE, legal_basis=FIXTURE`,
regardless of which acquisition strategy actually served the request, because that is
what genuinely happened.

Each spider's `source_id` (and so its `fare_quote.source_id`) still points at the
*real* source row — `airline_indigo`, not `fixture_replay` — because that is what the
data actually represents. `apix_core.provenance.resolve.resolve()` already documents
this exact split: a `FIXTURE`-basis quote's `policy_decision` link is expected to come
back `None`, because the decision that authorised the fetch was recorded against
`fixture_replay`, not the semantic source.

## Layout

```
fixtures/
├── airline_indigo/
│   └── DEL-BOM.json          # JsonEndpointStrategy fixture
├── airline_akasa/
│   ├── DEL-BOM.json          # JsonEndpointStrategy fixture (primary path)
│   └── BOM-DEL.html          # RenderedPageStrategy fixture (fallback path — this
│                              # route deliberately has no .json fixture, so a test
│                              # run genuinely exercises the JSON->rendered fallback)
├── ota_cleartrip/
│   └── DEL-BOM.html          # RenderedPageStrategy fixture (Cleartrip has no single
│                              # JSON endpoint worth replaying — see its spider)
└── drift/                    # SchemaDriftError capture — see "When a mapper drifts"
```

A spider's fixture URL is always `<fixture-server-root>/<source_code>/<ROUTE>.<ext>`,
so a mapper can be pointed at a specific captured payload by route code alone (see
`apix_collector.spiders.*.build_url`).

## Recording procedure

Recording a fixture means capturing one real response from a source and cutting it
down to exactly the bytes a mapper needs — never inventing or hand-editing the
*values* inside it (CLAUDE.md guardrail: "No fabricated data"). Only cosmetic
minimisation (whitespace, unrelated fields the mapper does not read, truncating a
result list to two or three itineraries) and mandatory scrubbing (below) are allowed.

1. **Only after the source is enabled.** A fixture is a recording of a real response;
   until `config/sources.yaml` marks a source `enabled: true` with a `PERMITTED`
   verdict, there is nothing to legally record. Fixtures for `airline_indigo`,
   `airline_akasa` and `ota_cleartrip` were written by hand against each source's
   publicly documented request/response shape for this phase, exactly as a
   first capture would look, and are labelled as such below — they are not yet backed
   by a real HTTP capture, because none of the three sources has cleared review.
   Replacing one with a genuine capture, once a source goes live, means repeating this
   procedure and overwriting the file in place.

2. **Capture the raw response.**
   * JSON endpoint (`JsonEndpointStrategy`): open the source's fare search in a
     browser, open devtools' Network tab, perform a search, and find the internal API
     call the results page makes. Save the response body verbatim
     (`Copy Response` / `Save response`).
   * Rendered page (`RenderedPageStrategy`): use Playwright's own trace/HTML dump
     rather than "View Source" — `page.content()` after the results have loaded, the
     same call `apix_collector.strategies.rendered_page.PlaywrightBrowserDriver.render`
     makes in production, so the fixture matches what the mapper will actually parse.

3. **Scrub before it touches the repository.** Every capture is reviewed for:
   * session tokens, cookies, auth headers, or anything identifying the machine or
     account that made the request — delete or replace with an obviously-fake value;
   * personal data of any kind (there should never be any in a fare search response —
     if there is, do not record it, and treat that as a finding to raise, not a fixture
     to ship);
   * anything under the source's copyright beyond what is needed to test parsing — trim
     unrelated boilerplate (unrelated nav/analytics JSON blocks, marketing HTML) that
     the mapper never reads.

4. **Name it `<ROUTE-CODE>.<ext>`** (`.json` for `JsonEndpointStrategy`, `.html` for
   `RenderedPageStrategy`) under `fixtures/<source_code>/`, matching a route code from
   `config/basket.yaml`.

5. **Write the test alongside it.** Every fixture in this repository has a
   corresponding test in `tests/collector/mappers/` that parses it and asserts on the
   resulting `RawQuote` fields, and (for the three shipped spiders) an end-to-end test
   in `tests/collector/spiders/` that runs the real spider against the real
   `FixtureServer`. A fixture with no test asserting its shape is a fixture nobody
   will notice breaking.

6. **Record when and how.** Note the capture date and method in the fixture's
   directory here (or in a comment at the top of the file, for formats that allow
   one) — the same spirit as `db/seeds/airports.csv`'s provenance header.

## Replaying fixtures

`apix_collector.fixtureserver.FixtureServer(fixtures_root)` serves `fixtures/` on an
OS-assigned loopback port. Every spider is constructed with a `fixture_base_url`
pointing at `<server.base_url>/<source_code>`, and fetches go through the real
`PolicyEngine` exactly as a live request would (see `apix_collector.registry` for how
`make collect-once` and `daily_sweep` both wire this up identically). No test, and no
current run of the collector, ever constructs an `httpx`/other HTTP client itself —
`tests/test_egress_only.py` enforces that statically.

## When a mapper drifts

If a source's response shape changes (a renamed field, a restructured payload), the
mapper raises `apix_collector.errors.SchemaDriftError`. Before it does, it calls
`apix_collector.drift.capture_drift`, which:

1. writes the offending payload to `fixtures/drift/<source_code>/<timestamp>.<ext>`;
2. logs one structured `collector_schema_drift` event with the reason and a
   `keys_added`/`keys_removed` diff against the mapper's known-good shape.

Nothing repairs the mapper automatically — that is deliberate (see
`apix_collector.drift`'s docstring). Fixing a drift means: read the captured payload,
update the mapper (and, once confident, the fixture it was tested against), and add a
regression test using the captured payload as the new fixture for the shape that broke
it.
