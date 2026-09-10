# APIx — What This Project Actually Does

A plain-language walkthrough of the whole system: what gets built, how data moves through it end to end, and every piece of the tech stack explained simply. This is a snapshot of the current codebase, not a spec — where something is a stub or placeholder, it says so.

---

## 1. The one-paragraph version

APIx measures how airfare prices in India are changing over time, the same way the government measures inflation for groceries or fuel. It does this by automatically visiting airline and travel-booking websites, recording what a ticket costs on a given route on a given day, cleaning up that raw data (removing junk, filling gaps honestly, flagging outliers), and then running proper index-number statistics on it — the same family of methods statistical agencies use for the Consumer Price Index. The result is a number (or a family of numbers, one per route and one national headline number) that is meant to be trustworthy enough for India's National Statistical Office (MoSPI) or the RBI to actually publish or use as an input. Every number the system produces can be traced backwards to the exact web page, the exact timestamp, and the exact method-version that produced it.

---

## 2. The end-to-end flow, in order

```
 ┌────────────┐     ┌──────────────┐     ┌───────────┐     ┌────────────┐     ┌───────────┐     ┌─────────────┐
 │  Scheduler │────▶│  PolicyEngine │────▶│  Collector │────▶│  Database  │────▶│  Cleaning  │────▶│  Index maths │
 │  (Prefect) │     │ (compliance)  │     │ (spiders)  │     │ fare_quote │     │  pipeline  │     │ (apix_core)  │
 └────────────┘     └──────────────┘     └───────────┘     └────────────┘     └────────────┘     └─────────────┘
                                                                                                          │
                                                                                                          ▼
 ┌────────────┐     ┌──────────────┐     ┌───────────┐                                          ┌─────────────┐
 │  Dashboard │◀────│  FastAPI     │◀────│  Postgres  │◀─────────────────────────────────────────│  index_run / │
 │  (React)   │     │  service     │     │ (Timescale)│                                          │  index_value │
 └────────────┘     └──────────────┘     └───────────┘                                          └─────────────┘
```

Walking through it in order:

1. **A schedule fires.** Prefect wakes up four times a day (02:00, 08:00, 14:00, 20:00 India time, each with a random delay so requests don't look like a bot hitting on the dot) and asks: for every route we care about, every "how far in advance was this ticket bought" bucket, and every airline/OTA source — go get today's price.
2. **Every single request is checked first.** Before any HTTP call happens, it must pass through the `PolicyEngine`: is this source currently allowed to be scraped, does `robots.txt` permit this exact path, are we under the rate limit, has the source's terms-of-service been reviewed and approved. If any check fails, nothing is fetched — the attempt is logged as a `PolicyDecision` either way.
3. **A spider fetches the page.** For sources with a JSON search API (like an airline's own booking backend), it's a plain HTTP GET. For sources that only render prices via JavaScript (some OTAs), a headless Chromium browser (Playwright) loads the page and reads the DOM. If a CAPTCHA shows up, the spider does not try to solve it — it marks the source blocked and moves on.
4. **The raw response is stored, unmodified, forever.** Every fare quote is written to an append-only database table (`fare_quote`) along with a hash of the exact URL and a hash of the raw response body, so it can never be silently altered later — corrections happen in a separate table, never by editing history.
5. **Cleaning turns raw quotes into an analysis-ready table.** Duplicate quotes for the same physical flight are recognised and merged, fares that only list a total are decomposed into base fare + taxes, statistically implausible quotes are flagged as outliers (not deleted), and cells with no observation are classified as either "genuinely sold out" or "we failed to collect it" — sold-out cells can be carefully imputed, but only with the imputation clearly labelled as such.
6. **The index maths run over the cleaned data.** This is real statistical-agency-grade index number theory: geometric-mean price relatives within each route/day cell, a multilateral method (GEKS-Törnqvist) that reconciles a rolling 13-month window all at once instead of naively chaining day-to-day, a hedonic regression that adjusts for quality differences (aircraft, stops, time of day) so the number reflects pure price change, and a splice method that extends the published series forward without ever revising numbers that have already been released.
7. **A run is stamped and persisted.** Every computed value records the exact data snapshot and exact method-config hash that produced it. Re-running the same stamp is required to reproduce the same output byte-for-byte.
8. **The API serves the result.** FastAPI exposes the published index values, per-route detail, methodology metadata, and (behind an API key) full drill-down provenance and raw microdata — plus an SDMX-JSON endpoint, the international standard format statistical agencies exchange data in.
9. **The dashboard shows it.** A React app visualises the headline index, route-level trends, lead-time (how price changes as departure approaches) curves, a "what happens if we tweak the method" console, and — importantly — a full audit trail: click a point on a chart and drill all the way down to the individual fare quote and the web page it came from.

---

## 3. The tech stack, explained simply

| Layer | Technology | What it's for, in plain terms |
|---|---|---|
| Language | Python 3.12 | The backend and all statistics code. |
| Dependency management | `uv` | Installs and pins exact package versions so everyone (and CI) runs identical code. |
| Type & style checking | `ruff`, `mypy --strict` | Catches bugs before running the code. `mypy --strict` is only enforced on the core statistics library — the part that must never silently misbehave. |
| Database | PostgreSQL 16 + TimescaleDB | A normal relational database, plus an extension that makes the huge `fare_quote` table (millions of price observations over time) fast to query by automatically splitting it into time-based chunks. |
| ORM / migrations | SQLAlchemy 2.0 + Alembic | SQLAlchemy is how Python code reads/writes the database with real objects instead of hand-written SQL everywhere. Alembic tracks every schema change as a numbered, forward-only migration file — nobody edits history, they add a new migration. |
| Web scraping (static) | Scrapy (its `parsel` selector library) | Extracts data out of HTML/JSON responses using CSS/XPath-style selectors. |
| Web scraping (JS pages) | Playwright | Runs a real (headless) Chromium browser for the handful of sites whose prices only appear after JavaScript runs — used only when a plain HTTP call can't get the data. |
| Orchestration | Prefect 3 | The scheduler. Decides when collection jobs run, retries failures, and gives visibility into every run. |
| Caching / rate limiting | Redis | Two jobs: (1) a shared "token bucket" so the system never hammers a source website faster than its policy allows, and (2) an API-response cache so repeated dashboard requests don't re-hit the database unnecessarily. |
| API framework | FastAPI + Pydantic v2 | Serves HTTP endpoints with automatic request/response validation and auto-generated documentation (OpenAPI 3.1). |
| Statistical data format | SDMX-JSON 2.0 | The standard format national statistical offices and international bodies (IMF, Eurostat, MoSPI's own eSankhyiki) use to exchange official statistics — one of the API's endpoints speaks this format natively. |
| Data science | pandas, numpy, statsmodels, scikit-learn | pandas/numpy do the table and array manipulation for index computation; statsmodels runs the regressions (hedonic quality-adjustment, the CPI "bridge" nowcast model); scikit-learn is available for any ML-flavoured pieces. |
| Frontend framework | React 18 + Vite + TypeScript | The dashboard's UI. Vite is the build tool/dev server (fast reloads); TypeScript adds type safety to the frontend code. |
| Frontend data fetching | TanStack Query | Manages calling the API, caching results in the browser, and automatically refetching when parameters (route, date, carrier) change. |
| Frontend charts | Apache ECharts | Draws the line charts, heatmaps, and the schematic route map. |
| Frontend styling | Tailwind CSS | Utility-class based styling instead of hand-written CSS files. |
| Testing | pytest, pytest-cov, hypothesis, schemathesis, Playwright (e2e) | pytest runs the test suite; hypothesis generates randomized edge-case inputs for the statistics functions; schemathesis checks the API actually matches its own OpenAPI contract; Playwright also drives browser-based end-to-end tests of the dashboard. |
| Local infra | Docker Compose | Spins up Postgres, Redis, Prefect, the API, and the dashboard together with one command for local development. |
| CI | GitHub Actions | Runs lint/tests automatically on every change. |

---

## 4. Walking through each part of the system

### 4.1 Collecting the data (`apps/collector/`, `apps/scheduler/`)

Three "spiders" exist today, one per data source:

- **IndigoSpider** — calls the airline's own internal JSON fare-search endpoint directly.
- **AkasaSpider** — tries the same JSON-endpoint approach first, and only falls back to rendering the page in a real browser if that fails.
- **CleartripSpider** — an online travel agency whose results page is assembled in the browser from several supplier calls under the hood, so there's no single JSON endpoint to call — it always uses the full browser-rendering path.

Every spider goes through a shared `BaseSpider`: it retries only genuinely retryable failures (server errors, rate-limit responses), backs off with increasing, randomized delays, and enforces a hard cap on how many requests one run is allowed to make. If a mapper (the code that turns a raw response into a structured price record) sees a shape it doesn't recognise — because the airline changed their page — it doesn't guess: it raises a "schema drift" flag and saves a sample for a human to look at, rather than silently producing wrong numbers.

**Important current state:** none of these spiders point at the real airline/OTA websites yet. `config/sources.yaml` still marks every real source as "not reviewed" and disabled — legal/ToS review hasn't happened. All three spiders are currently wired against a small local fixture server that replays recorded sample responses, so the whole pipeline can be built, tested, and demonstrated safely before a single real request goes out to a live airline site.

**Prefect** runs one real flow, `daily_sweep`, four times a day. It works out every (route, advance-purchase window, source) combination that needs a fresh price, respects a per-source concurrency limit, and is idempotent — re-running the same day's sweep won't create duplicate work, thanks to caching keyed on the exact parameters. Index computation and the "nowcast"/watchdog checks are, for now, run as manual command-line scripts (`make index-run`, `make nowcast-run`, `make watchdog-probe`) rather than their own Prefect flows — the scheduling automation currently covers only the collection step.

### 4.2 The compliance gate (`packages/apix_core/policy/`)

This is arguably the most important module in the whole system, because it's the one place the project's legal safety depends on. The `PolicyEngine` is the *only* code in the entire codebase allowed to make an outbound HTTP request to an external site — this is enforced not just by convention but by an automated test that scans the code for any other module trying to import an HTTP client.

Before fetching anything, four checks run in order, and the outcome (allowed or denied) is always logged:
1. Is this source currently enabled, not in a "cooling off" period, and has its terms-of-service been reviewed as permitted within the last 6 months?
2. Does the site's `robots.txt` allow fetching this exact path?
3. Is this path on the source's configured allow-list (and not on its block-list)?
4. Is there rate-limit budget left (a shared, Redis-backed token bucket plus an hourly hard cap plus a minimum delay between requests)?

If a response comes back looking like a CAPTCHA or bot-challenge page (reCAPTCHA, hCaptcha, Cloudflare, Akamai, and a few others are specifically detected), the source is disabled on the spot — there is no CAPTCHA solver anywhere in this codebase, by design.

### 4.3 Cleaning the raw data (`packages/apix_core/clean/`)

Raw quotes are never used directly for the index — they pass through a pipeline of pure functions:

- **Dedup** groups quotes that are really the same physical flight (same airline, flight number, travel date, similar departure time) so multiple sources quoting the same flight don't get double-counted.
- **Decompose** splits a total fare into base fare, taxes, and airport fees when a source only publishes the total — using the airport's published fee schedule. If it can't be worked out cleanly, it's labelled "undetermined" rather than guessed.
- **Outlier detection** runs two independent statistical screens (a robust z-score based on median absolute deviation, and the classic Tukey box-plot fence) on log fares within each route/day/advance-window group. Both scores are always computed; the config decides which one actually excludes a point from the index, and either way the row keeps both flags for auditing.
- **Missing-cell handling** figures out *why* an expected price observation is missing — genuinely sold out, versus the collector simply failed — and only imputes (fills in an estimate for) cells that look genuinely sold out, always marking the row `imputed = true` with a reason.
- **Quality gates** run a set of sanity checks (is this fare a plausible amount for this distance, is the tax share plausible, is coverage above a minimum threshold, are there any duplicate IDs) before an index run is even allowed to proceed — a failure blocks the run rather than producing a number quietly built on bad data.

### 4.4 The index maths (`packages/apix_core/index/`)

This is where "cleaned prices" becomes "an index number," and it deliberately mirrors how real consumer price indices are built:

- **Elementary aggregation** — within the smallest cell (one route, one day, one advance-purchase window), multiple price observations are combined using the *Jevons* formula (a geometric mean of price ratios) — the standard choice international guidelines (ILO/Eurostat) recommend when there's no reliable way to weight individual prices by sales volume.
- **Multilateral aggregation (GEKS-Törnqvist)** — rather than just comparing "today vs. yesterday" and chaining that forward (which drifts badly when the mix of flights/fares changes over time), the system reconciles an entire rolling 13-month window of periods against each other simultaneously and averages the comparisons. This is the same family of method national statistical offices increasingly use for products (like flights, or online goods) where item availability turns over quickly.
- **Hedonic quality adjustment** — a regression that holds flight characteristics (number of stops, time of day, how far in advance it was booked, aircraft/carrier) constant, so that a shift toward, say, more nonstop premium flights doesn't get mistaken for a "price increase."
- **Splicing** — once the multilateral window has been computed, only the newest period gets appended onto the already-published series, using its window-implied growth rate — so index values that have already been released to the public are never revised away.
- **Weighting up to a route, then a national number** — advance-purchase windows are combined into one route index using a booking-profile of ticket-purchase timing (currently a documented *assumption* pending real ticket-sales data, clearly labelled as such rather than presented as measured), and routes are combined into the national headline number weighted by each route's share of air passengers — a route with no real passenger-share data yet is excluded from the national number rather than being given a made-up weight.

Every one of these is a pure function — no database access, no logging — so it can be tested against hand-computed examples exactly like the underlying formula from a textbook, and given the same inputs it will always produce the same output.

### 4.5 Nowcasting (`packages/apix_core/nowcast/`)

This is a separate, clearly-labelled layer of *estimates*, not published index values:
- A **bridge model** estimates what the official CPI airfare sub-index will likely read before that official number is actually released, based on the relationship between APIx's own faster-moving index and past CPI prints.
- An **ATF pass-through model** estimates how much of a change in jet fuel prices historically shows up in fares, and with what delay.
- A **movement decomposition** splits a period's price change into how much came from pure price change versus a shift in carrier mix, booking-window mix, route mix, or tax/fee changes — the five pieces are built to add up exactly to the total observed change.

### 4.6 Provenance and the audit trail (`packages/apix_core/provenance/`)

Every fare quote is stamped, at collection time, with a hash of the exact URL it came from and a hash of the exact raw response body, and the raw response itself is saved to content-addressed storage (named by its own hash, so tampering or corruption is immediately detectable on retrieval). A single `resolve()` function can walk from any fare quote all the way back through the collection run, the source, and the specific policy decision that authorised fetching it — and it deliberately raises an error rather than returning a partial answer if any link in that chain is missing.

### 4.7 The database (`db/`)

Postgres 16 with the TimescaleDB extension. The `fare_quote` table — the raw, ever-growing observation log — is a Timescale "hypertable," automatically split into 7-day chunks so it stays fast to query even with millions of rows, and it is enforced as append-only at the database level (update/delete are turned into no-ops by database rules, not just application code). Migrations are applied one at a time, forward only, and cover: the base schema (reference data, collection/policy tables, index tables, quotes), adding a `SYNTHETIC` data tag so test data can never be confused with real collected data, adding API keys and an explicit "which quotes fed this published number" lineage table, adding reference tables for jet-fuel prices / official CPI / DGCA fare data / rail fares (all schema-only until real official data is loaded), and adding tables for the "watchdog" personalised-pricing probe.

Seed data (`db/seeds/`) is deliberately minimal and real: an open-data list of Indian airports and a DGCA-derived list of Indian carriers — no synthetic or invented reference data is ever seeded. Routes come from the config file, not a seed table, so there's exactly one source of truth for which city-pairs are in the basket.

### 4.8 Configuration (`config/`)

Nothing about the method — which formula, which window length, which outlier rule, which sources are allowed — is hard-coded. It all lives in versioned YAML files, each validated against a Pydantic schema (so a typo or an invalid combination is rejected loudly at load time, not silently ignored), and every config file is hashed. That hash, paired with a hash of the input data snapshot, is what makes an index run reproducible: given the same two hashes, re-running produces the identical output.

### 4.9 The API (`apps/api/`)

A FastAPI service. Every request passes through a small pipeline: a correlation ID is attached for tracing, an API key (if present) is resolved into a role (public / researcher / official), a rate limit is checked, and any error is returned in a standard machine-readable format (RFC 9457 "problem" documents) rather than an ad hoc error shape.

Public, no-key-needed endpoints serve published index values, per-route series, metadata about the current method and basket, coverage/heatmap views, and an SDMX-JSON endpoint for interoperability with other statistical systems. Endpoints that expose individual fare quotes, raw provenance detail, CSV export, or a "what if we changed the method" preview all require an API key belonging to a researcher or official — because those surfaces expose microdata or unpublished/draft figures, not the finished public statistic. Two endpoints (`decomposition`, `nowcast`) are intentionally left returning "not implemented yet" rather than being backed by an invented methodology — consistent with the project's rule of never fabricating a number.

### 4.10 The dashboard (`apps/web/`)

A React application with six main screens:
- **Overview** — the headline index number, today's movers, coverage stats, and a small route map.
- **Route Explorer** — a chosen route's fare trend, split either by how far in advance tickets were bought or by carrier.
- **Lead Time** — how average fare changes the closer you get to departure, with the "sweet spot" where price stops falling marked automatically.
- **Method Console** — an interactive "what if" tool: change a methodology setting (formula, window length, imputation rule, etc.) and see, live, how the resulting index would have looked differently, compared side-by-side against what's actually published.
- **Audit** — the accountability screen. Click a point on the headline chart, drill into which routes contributed to it, drill into which individual cleaned fare quotes fed that route number, and drill one level further into the exact source, timestamp, and legal basis for that specific quote. Also shows a full revision history and lets you ask "what did this number look like as published on an earlier date."
- **Sector Heatmap** — routes vs. time, colored by how far each route currently sits from its own historical average.

The dashboard talks to the API through a fully-typed client generated straight from the API's own OpenAPI schema, so the frontend and backend can't silently drift apart. Charts are built with a shared, accessible chart component (keyboard navigation and screen-reader announcements included) rather than each screen re-implementing chart wiring from scratch.

### 4.11 Testing (`tests/`, `fixtures/`)

No test ever makes a real network call. Spider tests run against a tiny local fixture server replaying recorded sample responses (a couple of real-shaped JSON/HTML files per source) through the *real* PolicyEngine and a *real* rate limiter — just pointed at localhost instead of the internet — so the compliance logic itself gets exercised, not mocked away. A larger, clearly-labelled synthetic dataset (about 269,000 generated fare quotes with known, deliberately-injected anomalies) is used to test that the outlier detection and index maths correctly recover a known "ground truth." The API's contract is tested end to end against a real seeded database: every endpoint's status codes, pagination shape, error format, and auth requirements are checked automatically, and the two "not implemented yet" endpoints are checked to actually return "not implemented" rather than a fake result.

---

## 5. Where things stand today (real vs. not-yet-real)

Being explicit about this, because it matters for a system whose whole premise is honesty about data:

| Already real / working | Still placeholder / not yet done |
|---|---|
| Full pipeline architecture: collector → policy engine → database → cleaning → index maths → API → dashboard | No spider is pointed at a real airline/OTA website yet — all three are wired to a local fixture replayer, pending ToS/legal review of each real source |
| Real reference data: Indian airports (open data) and DGCA-listed carriers | Route passenger-share weights (`dgca_pax_share`), and the reference tables for real DGCA fare data, jet-fuel prices, and official CPI figures are schema-ready but empty until official data is loaded |
| Full index-number methodology implemented and unit-tested against hand-computed and synthetic-ground-truth cases | Booking-profile (advance-purchase) weights are a documented *assumption*, explicitly flagged as not-yet-measured |
| Compliance engine (robots.txt, rate limiting, ToS gating, CAPTCHA detection) fully implemented and tested | Two API/index endpoints (`/v1/decomposition`, `/v1/nowcast`) deliberately return "not implemented" rather than a computed answer |
| Prefect-scheduled collection sweeps, four times daily | Index computation, nowcasting, and the watchdog probe are run manually via CLI commands, not yet automated as their own scheduled flows |
| Full FastAPI service with auth, caching, pagination, SDMX-JSON, and a real OpenAPI contract | — |
| Full React dashboard with six working screens, generated-from-schema API client | Dark mode is intentionally disabled (hardcoded to light) after an earlier OS-following version broke the design |

---

## 6. The principles that shape every design decision here

These come straight from the project's own ground rules, and you can see all of them reflected directly in the code described above:

1. **Every number must be traceable** back to the individual quotes, and every quote back to its exact source and timestamp — this is why `provenance/` and the Audit dashboard screen exist.
2. **Nothing fails silently** — blocked sources, missing routes, dropped outliers, and imputed values are all explicitly recorded with a reason, never just absent.
3. **Compliance lives in code, not a policy document** — the `PolicyEngine` is the single, enforced gateway for every outbound request.
4. **Reproducibility** — every run is stamped with a data-snapshot hash and a method-config hash; the same stamp must always reproduce the same output.
5. **No fabricated data, ever** — if real data isn't available yet (DGCA weights, CPI figures, an unimplemented model), the code says so explicitly rather than inventing a plausible-looking number.
