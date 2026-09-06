# APIx — Real-time Airfare Price Index for India

## What this project is

APIx is a statistical production system, not a flight-price tracker. It collects airfare
quotes from Indian airline and OTA websites, cleans and normalises them, and computes an
official-quality price index intended for consumption by MoSPI (the National Statistical
Office) and the RBI, to augment the Transport sub-group of the Consumer Price Index.

The output is a number that a national statistics office must be willing to publish.
That constraint drives every design decision in this repo. When you face a trade-off
between convenience and auditability, choose auditability.

## Non-negotiable principles

1. **Every published number is traceable.** Any index value must be resolvable back to the
   individual fare quotes that produced it, and each quote back to its source, timestamp
   and legal basis. Never introduce a code path that produces a number without provenance.
2. **Nothing fails silently.** A blocked source, a missing route, a dropped outlier and an
   imputed value are all recorded as such, with a reason. Empty results are data, not gaps.
3. **Compliance is enforced in code, not documented in a README.** No HTTP request to an
   external source may be made without passing through the PolicyEngine first.
4. **Reproducibility.** An index run is stamped with a data-snapshot id and a method-config
   hash. Re-running the same stamp must produce byte-identical output.
5. **No fabricated data.** Never invent DGCA figures, CPI values, passenger weights or fare
   data to make something run. If real data is unavailable, raise `NotImplementedError`
   with a clear message, or use the explicitly-labelled fixture dataset.

## Repository layout

```
apix/
├── CLAUDE.md
├── README.md
├── compose.yml
├── .env.example
├── pyproject.toml              # uv/hatch workspace root
├── apps/
│   ├── api/                    # FastAPI service
│   ├── collector/              # Scrapy + Playwright spiders
│   ├── scheduler/              # Prefect flows
│   └── web/                    # React + Vite dashboard
├── packages/
│   └── apix_core/              # shared library — the only place index maths lives
│       ├── config/
│       ├── models/             # SQLAlchemy models + Pydantic schemas
│       ├── policy/             # compliance engine
│       ├── clean/              # normalisation, decomposition, imputation
│       ├── index/              # elementary aggregates, multilateral, hedonics
│       ├── nowcast/            # bridge model
│       └── provenance/
├── db/
│   ├── migrations/             # Alembic
│   └── seeds/                  # routes, carriers, airports — real reference data
├── fixtures/                   # recorded HTTP responses + synthetic fare dataset
├── infra/
├── tests/
└── docs/
    ├── methodology.md          # generated from running config, never hand-edited
    └── adr/                    # architecture decision records
```

## Tech stack — pinned, do not substitute

- Python 3.12, `uv` for dependency management, `ruff` + `mypy --strict` on `apix_core`
- PostgreSQL 16 + TimescaleDB (hypertable on `fare_quote`)
- SQLAlchemy 2.0 (typed, async where the API touches it), Alembic for migrations
- Scrapy for static sources, Playwright for JS-rendered sources
- Prefect 3 for orchestration, Redis for rate-limit token buckets and caching
- FastAPI + Pydantic v2 for the API; OpenAPI 3.1 generated, SDMX-JSON 2.0 for the
  statistical endpoints
- pandas, numpy, statsmodels, scikit-learn for the index and nowcast maths
- React 18 + Vite + TypeScript, TanStack Query, ECharts, TailwindCSS
- pytest, pytest-cov, hypothesis, schemathesis, Playwright (e2e)
- Docker Compose for local and staging; GitHub Actions for CI

## Coding conventions

- **Type everything.** `mypy --strict` must pass on `packages/apix_core`. No `Any` without
  a `# type: ignore[...]` carrying a reason.
- **Index maths are pure functions.** Everything in `apix_core/index/` takes and returns
  dataframes or arrays. No database access, no I/O, no logging side-effects. This is what
  makes them testable against hand-computed fixtures.
- **Config over constants.** Route baskets, weights, method choices and source policies live
  in versioned YAML under `config/`, never hard-coded. Every config file has a Pydantic
  schema and is validated on load.
- **Structured logging only** (`structlog`, JSON output). Every log line carries `run_id`.
- **Migrations are forward-only.** Never edit an applied migration; add a new one.
- **Dependencies are pinned** to exact versions in `pyproject.toml`. Do not add a dependency
  without stating why in the commit message.

## Guardrails — things you must never do

- Never make an outbound request to a source website except through `PolicyEngine.request()`.
- Never authenticate to, log in to, or hold credentials for any airline or OTA site.
- Never attempt to solve, bypass or outsource a CAPTCHA. If a source presents one, mark the
  source blocked, record the reason, and move on.
- Never carry a stale price forward to fill a gap without setting `imputed = true` and
  recording `imputation_method`.
- Never delete or mutate a row in `fare_quote`. It is append-only. Corrections happen in
  `fare_quote_clean` and are logged.
- Never commit secrets, API keys, proxy credentials or `.env`. Only `.env.example`.
- Never write a test that hits the live internet. All spider tests use recorded fixtures.
- Never hand-edit `docs/methodology.md` — it is generated.

## Definition of done for any task

- `make lint` passes (ruff + mypy)
- `make test` passes and coverage on `packages/apix_core` is ≥ 80%
- `make up` brings the full stack up cleanly from scratch
- New behaviour has a test; new config has a schema; new endpoints appear in OpenAPI
- If the change affects the index method, `docs/methodology.md` regenerates and a row is
  added to the revision log

## Useful commands

```
make up          # docker compose up, migrate, seed reference data
make down
make lint
make test
make collect-once ROUTE=DEL-BOM   # single collection run against fixtures
make index-run DATE=2026-09-01    # compute index for a date
make seed-synthetic DAYS=90       # generate the labelled synthetic dataset
```