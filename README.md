# APIx — Real-time Airfare Price Index for India

APIx collects airfare quotes from Indian airline and OTA websites, cleans and normalises
them, and computes an official-quality price index intended for MoSPI and the RBI to
augment the Transport sub-group of the Consumer Price Index.

It is a statistical production system, not a flight-price tracker. The output is a number
a national statistics office must be willing to publish, and that constraint drives every
design decision here. See [CLAUDE.md](CLAUDE.md) for the full contract.

## Status: Phase 2 — collectors, in progress

What exists today:

| Area | State |
|---|---|
| Workspace, tooling, CI | Working. `make lint` and `make test` are real. |
| Data model + first migration | Complete. 16 tables, TimescaleDB hypertable, append-only enforcement. |
| API contract | All 22 endpoints, OpenAPI 3.1, RFC 9457 errors, cursor pagination. |
| Config schemas | Complete: basket (50 routes), sources (10), method. Validated on load. |
| Infrastructure | compose stack, three multi-stage non-root images, CI. |
| Collectors | `BaseSpider`, `JsonEndpointStrategy`/`RenderedPageStrategy`, three spiders + mappers (IndiGo, Akasa, Cleartrip), schema-drift capture, and `apix_scheduler.flows.daily_sweep` (Prefect). Every real source still `NOT_REVIEWED`/disabled pending legal review, so every fetch today replays a recorded fixture through the real `PolicyEngine` over a loopback server — see [ADR 0003](docs/adr/0003-fixture-replay-over-loopback.md) and [`docs/fixtures.md`](docs/fixtures.md). |
| Cleaning, index maths, nowcast, DGCA weights | **Not implemented** (Phases 2–4). |

> **The API serves example data.** Every `/v1` response carries
> `meta.data_status = "EXAMPLE_ONLY"` and the header `X-APIx-Data-Status: EXAMPLE_ONLY`.
> The values are deliberately round and obviously synthetic. The purpose of this phase is
> to freeze the contract so the front end can be built against it, not to publish numbers.
> The two exceptions are `/v1/metadata/basket` and `/v1/metadata/method`, which serve the
> real, validated contents of `config/` — the basket and the method exist today.
>
> No airfare has been collected. No `dgca_pax_share` has been invented: every route's
> weight is `null` until Phase 2 loads the real DGCA release, and a test enforces that.

## Run it

```bash
cp .env.example .env      # edit the CHANGEME values
make up                   # compose up --wait, then migrate
```

Then:

- API docs — http://localhost:8000/docs
- OpenAPI 3.1 — http://localhost:8000/openapi.json
- Dashboard — http://localhost:5173
- Prefect — http://localhost:4200

Requires Docker with Compose v2, and [uv](https://docs.astral.sh/uv/) for the local
Python toolchain.

## Develop

```bash
make install          # resolve and install the workspace into .venv
make lint             # ruff check + ruff format --check + mypy (strict on apix_core)
make test             # pytest with the >=80% coverage gate on apix_core
make test-integration # tests needing a container runtime (Postgres, Redis)
make seed             # airports, carriers, the route basket, and sources
make collect-once ROUTE=DEL-BOM  # run all three spiders against fixtures for one route
make openapi          # regenerate docs/openapi.json for the front end
make down
```

`make test` skips the container-backed tests when no runtime is present, so it is useful
on a laptop and complete in CI. No test in this repository touches the live internet.

## Repository map

```
apix/
├── CLAUDE.md                   the contract for this repository; read it first
├── compose.yml                 postgres+timescale, redis, api, web, prefect, migrate
├── pyproject.toml              uv workspace root; every dependency pinned exactly
├── Makefile                    the commands above
├── alembic.ini                 URL comes from the environment, never from this file
│
├── packages/apix_core/         the shared library — depends on nothing else in here
│   └── src/apix_core/
│       ├── settings.py         env-var settings, validated; robots compliance is
│       │                       rejected at load time if switched off
│       ├── config/             Pydantic schemas + loaders for config/*.yaml
│       ├── models/             SQLAlchemy 2.0 models — the single data-model definition
│       ├── policy/             PolicyEngine: the ONLY egress path to a source site
│       ├── clean/              normalisation, outliers, imputation      (Phase 2)
│       ├── index/              elementary, multilateral, hedonics       (Phase 3)
│       ├── nowcast/            bridge model                             (Phase 4)
│       └── provenance/         index value -> quotes -> source          (Phase 3)
│
├── apps/
│   ├── api/                    FastAPI service; OpenAPI 3.1 + SDMX-JSON 2.0
│   ├── collector/              Scrapy-style spiders + Playwright; fixture-replay today
│   ├── scheduler/              Prefect 3 flows — daily_sweep
│   └── web/                    React 18 + Vite + TS + TanStack + ECharts
│
├── config/
│   ├── basket.yaml             50 directional city-pairs, AP windows, basket version
│   ├── sources.yaml            one entry per source with its full compliance position
│   └── method.yaml             the index method, as hashed data
│
├── db/
│   ├── migrations/             Alembic; forward-only, never edit an applied revision
│   └── seeds/                  real reference data (airports, carriers)
│
├── infra/docker/               multi-stage, non-root images for api, collector, web
├── fixtures/                   recorded responses (docs/fixtures.md) + synthetic dataset
├── tests/                      mirrors the source tree
└── docs/
    ├── adr/                    architecture decision records
    ├── methodology.md          GENERATED from config/method.yaml — never hand-edited
    └── openapi.json            GENERATED by `make openapi`
```

## The five things this repository will not do

Enforced in code and asserted by tests, not left to a reviewer's memory:

1. **No number without provenance.** `/v1/provenance/{quote_id}` resolves any observation
   to its source, timestamp and legal basis. `index_value` is keyed by `index_run`, so
   vintages survive and revisions are visible rather than silent.
2. **Nothing fails silently.** `fare_quote_clean` has check constraints that reject an
   outlier without a rule, an imputation without a method, or a row with neither a raw
   quote behind it nor an imputation flag. `/v1/coverage` reports gaps as data.
3. **Compliance is code.** Every outbound request goes through `PolicyEngine.request`
   (or, when a browser must do the fetching, `PolicyEngine.check` first — see ADR 0003).
   `PolicyEngine` refuses to even start around a config where an enabled source lacks a
   `PERMITTED`, recently-reviewed ToS verdict. `APIX_RESPECT_ROBOTS=false` is rejected at
   settings load. Every real source ships disabled today, pending legal review.
4. **Reproducibility.** An index run is stamped with a `data_snapshot` id and a
   `method_config` hash. The same stamp must produce byte-identical output.
5. **No fabricated data.** Every `dgca_pax_share` is `null`. `BasketConfig` rejects a
   partially-populated weight vector, so the basket cannot become half-real.

`fare_quote` is append-only, enforced by PostgreSQL rules that make `UPDATE` and `DELETE`
no-ops. Corrections happen in `fare_quote_clean` and are logged.

## Data model at a glance

```
airport ─┬─> route ──┬─> fare_quote ──> fare_quote_clean ──> index_value
carrier ─┘           │        ▲                 │                 ▲
                     │        │                 │                 │
source ──> source_policy      │           data_snapshot ──> index_run <── method_config
  │                           │                                   │
  ├──> policy_decision        │                              revision_log
  └──> collection_run ────────┘                              nowcast_value
```

`fare_quote` is a TimescaleDB hypertable on `collected_at`. Timescale requires the
partition column in every unique index, so its primary key is `(id, collected_at)` and
`fare_quote_clean` carries `quote_collected_at` alongside `quote_id` to keep the lineage
a real foreign key. See [ADR 0002](docs/adr/0002-why-multilateral-index.md) for the index
method, and the docstring on `db/migrations/versions/0001_initial_schema.py` for the
schema decisions.

## Next

Rest of Phase 2: the cleaning pipeline (`apix_core/clean/`), loading real DGCA passenger
weights into the basket, and legal review of the first real source so a spider has
something live to fetch from.
