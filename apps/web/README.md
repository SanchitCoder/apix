# APIx Dashboard

The web front end for APIx — the real-time airfare price index for India. This document
describes what was built in `apps/web` (the dashboard) and the parts of `apps/api` it
depends on, screen by screen and component by component, and explains why each piece
exists in terms of the people who actually have to use it.

See the root [`CLAUDE.md`](../../CLAUDE.md) for the statistical-production constraints
this whole system is built under. This README assumes that context and focuses on the
dashboard specifically.

---

## 1. Who this is for

APIx is not a consumer flight-price app. It exists to produce a number — an official
price index — that a national statistics office is willing to publish and that a central
bank is willing to feed into a policy decision. The dashboard's actual audience is
narrow and specific:

| Who | What they need from this dashboard |
|---|---|
| **MoSPI methodologists** (National Statistical Office) | To see the index is built correctly, to trial method changes before they become policy, and to defend any published number back to its source data on demand. |
| **RBI analysts** | A fast, honest read on where airfares are moving *this month*, clearly separated from anything not yet final — a nowcast is not a published value, and the dashboard never lets the two look the same. |
| **APIx's own statisticians/data engineers** | A way to see collection health day to day (what sources are blocked, what routes are missing) without reading logs. |
| **An external auditor or a future FOI request** | A click-path from any chart point down to the exact raw quote, its source, and the legal basis it was collected under. |

Every screen below is designed against one of these four needs, not against "what does a
nice-looking index dashboard usually have."

---

## 2. Why a dashboard needs to look like this

A generic financial dashboard optimizes for a clean headline number. This one can't,
because of a constraint that shapes every screen: **a number without provenance is not
allowed to exist in this system** (`CLAUDE.md` principle 1). That single rule is why the
dashboard has an entire screen (§3.6) devoted to nothing but clicking a chart point and
walking down to a raw quote, and why every other chart carries a visible "what you're
looking at" status rather than presenting a number and trusting the viewer to assume
it's real.

Two more constraints from `CLAUDE.md` show up directly in the UI, not just the backend:

- **"Nothing fails silently"** → the data-freshness strip and the coverage indicator on
  the Overview screen exist specifically so a blocked source or a missing route is
  something you *see*, not something you discover three weeks later when a number looks
  wrong.
- **"No fabricated data"** → `dgca_pax_share` (route weight) is shown as literally empty
  everywhere it appears, rather than backfilled with a guess, because Phase 2 hasn't
  loaded the real DGCA passenger-share release yet. The dashboard would rather show a
  blank than a plausible-looking made-up number.

---

## 3. The six screens

### 3.1 Index overview (`/`)

**Serves:** RBI analysts and MoSPI, first thing each morning.

- **Headline APIx** value with month-over-month and year-over-year change. The index is
  monthly (`config/method.yaml`), so "day/week" deltas would be meaningless for this
  series — rather than fabricate a daily number, the tiles show real MoM/YoY changes and
  say plainly *"fewer than 13 months of published history"* when YoY can't be computed
  yet, instead of hiding the tile or showing a fake zero.
- **APIx headline vs. the official CPI air-fare series**, on one shared axis (never
  dual-axis — see the dataviz skill's anti-pattern list), so a reader can see at a glance
  whether APIx is leading, lagging, or diverging from the number MoSPI already publishes.
- **Data-freshness strip**: one badge per source (`fixture_replay`, `ota_makemytrip`,
  ...), each showing OK / PARTIAL / BLOCKED / DISABLED / ERROR with the reason inline.
  This is `/v1/coverage` rendered as something a person can scan in two seconds instead
  of a JSON blob.
- **Coverage indicator**: routes covered vs. expected today, with the actual missing
  route codes listed — not just a percentage.

### 3.2 Route explorer (`/routes`)

**Serves:** methodologists investigating one corridor; RBI analysts checking whether a
price move is broad-based or one route.

- Route selector bound to the **real** 50-route basket (`/v1/metadata/basket`), not a
  stub list.
- Fare curve over time, splittable by **advance-purchase window** or by **carrier** —
  toggle, don't juggle six charts.
- Periods where the cheapest window fully sold out are **shaded**, not silently plotted
  as if a price existed. A sold-out cell isn't a price point; treating it as one would be
  exactly the kind of silent gap-filling `CLAUDE.md` forbids.
- **Corridor momentum map**: a schematic (not a real basemap — there's no India GeoJSON
  bundled) plot of the routes with known airport coordinates, coloured on the shared
  diverging scale by period-over-period change. Deliberately limited to the three
  airports whose coordinates exist in `db/seeds/airports.csv` today, rather than
  interpolating positions for the rest of the basket.

### 3.3 Sector heatmap (`/heatmap`)

**Serves:** spotting which routes are behaving unusually *for themselves* — a busy
holiday corridor and a quiet regional one shouldn't be compared on the same absolute
scale.

- Routes × periods grid, coloured by **deviation from each route's own baseline**
  (its own mean over the window shown), not by absolute price level. A route that's
  always expensive doesn't light up red just for being expensive.
- Diverging colour scale centred on zero, using the validated diverging pair (blue↔red)
  from the shared theme — never a rainbow, never a hue sitting at the "nothing happened"
  midpoint.

### 3.4 Lead-time curve (`/leadtime`)

**Serves:** understanding *when* to buy, and validating the shape of the curve the index
methodology assumes (`config/basket.yaml`'s seven advance-purchase windows exist because
this curve is real and material).

- Mean fare against days-to-departure, per route and optionally per carrier.
- **Interquartile band** (P25–P75) drawn around the mean, because an airfare
  distribution is right-skewed — a single mean line without dispersion would misstate
  how much a traveller might actually pay.
- The **inflection point** (the window past which buying earlier stops helping) is
  marked explicitly rather than left for the reader to eyeball off a line chart.

### 3.5 Method console (`/method`) — the differentiator

**Serves:** the one audience this whole project exists for: a MoSPI methodologist
deciding whether to *change how the index is computed*.

This is the screen `CLAUDE.md` calls out as needing real care, because it's where a
statistician can ask "what if we used Fisher instead of Törnqvist, or a 24-month window
instead of 13" **without touching `config/method.yaml`** — and see the answer against a
live preview run, not a mockup.

- Controls bound one-to-one to the real method schema
  (`packages/apix_core/config/method.py`): elementary formula (Jevons/Dutot/Carli),
  multilateral method (GEKS-Törnqvist/Fisher, time-product-dummy, Geary-Khamis), rolling
  window length, splice method, imputation rule, quality-adjustment toggle.
- Every change **POSTs to `/v1/method/preview`**, which re-validates the merged
  configuration through the *exact same* Pydantic schema that validates
  `config/method.yaml` on disk. Ask for Carli (rejected as biased, fails the
  time-reversal test) and the console shows the server's real 422 rejection — it can't
  silently offer a method the system would refuse to publish.
- The preview chart always draws the **method-in-force line alongside the preview
  line**, so a reviewer sees exactly what moved, not just a new number floating alone.
- **Diagnostics travel with the preview**: coverage %, quote count, imputed-cell count,
  outlier-dropped count, suppressed-cell count — the exact evidence a statistician needs
  to judge whether a method change is defensible, not just whether it "looks nicer."
- The preview's own **config hash** is shown, distinct from the hash of the method
  currently in force, so adopting a preview is traceable: it becomes a reviewed change to
  `config/method.yaml`, never a silent divergence between what's shown and what's
  published.

### 3.6 Audit and provenance (`/audit`)

**Serves:** anyone who has to answer "where did this number come from" — an auditor, a
journalist FOI request, or MoSPI's own internal review before publication.

This is `CLAUDE.md` principle 1 made clickable:

```
index value  →  contributing route indices  →  cleaned quotes  →  raw source
```

- Click (or keyboard-activate) any point on the headline chart to open a drill-down.
- **Level 2 — Contributing route indices** (`/v1/index/contributors`): every route that
  fed into that headline value, with its own index and quote count. Weight and
  contribution-in-percentage-points are shown as **null**, not estimated, until Phase 2
  loads real DGCA passenger shares — an honest "we don't have this yet" instead of a
  number that looks precise but isn't real.
- **Level 3 — Cleaned quotes** (`/v1/quotes`): the individual observations behind that
  route, each tagged with its treatment — clean, **outlier** (with the rule that flagged
  it), or **imputed** (with the method used). A quote that was dropped or filled in is
  shown as such, not hidden from the list.
- **Level 4 — Source and legal basis** (`/v1/provenance/{quote_id}`): the terminal node.
  Source display name, legal basis, the PolicyEngine's policy decision, collection
  timestamp, and the source-URL and content hashes that let anyone verify the payload
  hasn't been altered since collection.
- **Vintage selector**: "what did we say this period's value was, as of this date" —
  because revisions happen, and a number that quietly changed without a trace would be
  worse than one that was simply wrong.
- **Revision log**: every change to a published value, including first publications
  (`old_value = null`), each with a stated reason. Nothing is overwritten in place.

---

## 4. What's under the hood

### 4.1 The typed API client — no hand-written `fetch` calls

`src/api/schema.d.ts` is generated straight from the API's own OpenAPI document:

```
make openapi                              # apps/api writes docs/openapi.json
npm run generate:api                      # openapi-typescript reads it into schema.d.ts
```

`src/api/client.ts` wraps that generated schema with `openapi-fetch`, and
`src/api/hooks.ts` is one TanStack Query hook per endpoint the dashboard uses. The
practical effect: if the API's contract changes, the dashboard fails to *type-check*, not
fails silently at runtime with a shape mismatch six months later. This is the same
philosophy as `CLAUDE.md`'s "config over constants, validated on load" — just applied to
the boundary between the two apps instead of to a YAML file.

### 4.2 The theme system — one source of truth for every colour

`src/theme/tokens.ts` defines the entire palette (categorical series order, sequential
ramp, diverging pair, status colours) once, for both light and dark mode. Every chart and
every panel reads from it — there is no per-chart colour literal anywhere in the six
screens. The palette was run through the design system's colour-vision-deficiency
validator before being adopted; see `src/theme/echartsTheme.ts` for how ECharts options
are built from the tokens (grid, tooltip, legend, axes, diverging ramp) so a chart author
never picks a raw hex value.

### 4.3 `EChart` — the keyboard layer every chart gets for free

`src/components/EChart.tsx` wraps ECharts' imperative API with one addition every screen
inherits automatically: **arrow-key navigation**. Left/Right walk the points of the
active series, Up/Down switch series, Enter/Space activates a point (this is what powers
the audit drill-down without a mouse), and the focused point's value is announced through
an `aria-live` region — so a keyboard user and a screen-reader user get the same
information a mouse user gets from hovering.

### 4.4 `ChartPanel` — the four states every chart has to handle

`src/components/ChartPanel.tsx` owns loading, error, empty, and **stale** states so no
screen has to invent its own. "Stale" is the one worth naming: when today's collection
run hasn't finished, the panel says so above the chart — it never draws a line down to
zero to paper over a gap. Every panel with a chart also carries a **data-table toggle**
(`src/components/DataTable.tsx`), so nothing in this dashboard is accessible only through
a canvas.

### 4.5 New API surface built specifically to power this dashboard

These endpoints didn't exist before this work and were added in `apps/api` to give the
six screens something real to bind to:

| Endpoint | Powers |
|---|---|
| `POST /v1/method/preview` | The Method Console — re-validates overrides through the real method schema. |
| `GET /v1/index/contributors` | Audit screen, drill-down level 2. |
| `GET /v1/index/revisions` | Audit screen's revision log. |
| `GET /v1/quotes` | Audit screen, drill-down level 3. |
| `GET /v1/metadata/carriers` | Carrier filters on Route Explorer and Lead-Time. |

Plus richer fields on existing endpoints: airport coordinates and `sold_out` /
`carrier_iata` on the route series (Route Explorer), quartile bands on the lead-time
buckets (Lead-Time Curve). Every one of these is covered by
`tests/api/test_contract.py` and appears in the generated `docs/openapi.json` the
dashboard's typed client is built from — nothing here is UI-only scaffolding sitting on
top of an untested endpoint.

---

## 5. Current status — read this before trusting a number on screen

**Every value in this dashboard today is a labelled placeholder.** `apps/api` is in
Phase 1: it serves hard-coded example payloads so the frontend contract could be built
and frozen before the collectors, cleaning pipeline, and index maths exist (Phases 2–4).
Two exceptions serve real data already: `/v1/metadata/basket` (the real 50-route basket)
and `/v1/metadata/method` (the real, validated `config/method.yaml`).

The dashboard makes this impossible to miss rather than burying it in a footnote:

- Every `/v1` response carries `meta.data_status = "EXAMPLE_ONLY"`.
- The dashboard shows a persistent amber banner while that's true.
- Every `ChartPanel` displays a "Example data" badge next to its title.

When Phase 3 wires the real database in, this dashboard requires **no changes** to keep
working correctly — the same components that render `EXAMPLE_ONLY` today will render
`PUBLISHED` and `PROVISIONAL` tomorrow, because the status is data-driven, not
hard-coded into the UI.

---

## 6. Running it

```bash
# from the repo root
make openapi                 # generate docs/openapi.json from the live API schema

cd apps/web
npm install
npm run generate:api         # generate the typed client from docs/openapi.json
npm run dev                  # http://localhost:5173

# in another terminal, from the repo root
uv run uvicorn apix_api.main:app --app-dir apps/api/src --port 8000
```

Or via Docker: `make up` brings up the whole stack, dashboard included, at the URLs
printed by the command.

### Checks

```bash
npm run lint          # tsc --noEmit — the same check CI runs
npm run build          # production build, code-split per screen route
npm run e2e:install     # one-time: download the Playwright browser
npm run e2e             # the four required end-to-end scenarios (see below)
```

The e2e suite (`e2e/dashboard.spec.ts`) covers: loading the overview, drilling into a
route in the Route Explorer, changing a Method Console control and observing the preview
index move, and completing one full provenance drill-down from a chart point down to a
source's legal basis. It boots both the API and the dev server itself
(`playwright.config.ts`), so `npm run e2e` is self-contained.

All six screens were verified against Lighthouse's accessibility audit at a score of
**100** (target was ≥95) in both themes.
