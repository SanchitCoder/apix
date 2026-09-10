# External data sources

What comes from where, under what basis, and what a human must do by hand.
Anything not listed here does not enter the system — principle 1 in `CLAUDE.md`.

## Airports — loaded, done

| | |
|---|---|
| Dataset | OurAirports `airports.csv` (community dataset, public domain / CC0) |
| URL | <https://davidmegginson.github.io/ourairports-data/airports.csv> |
| Retrieved | 2026-09-04 |
| Filter | `iso_country=IN`, `scheduled_service=yes`, IATA code present → 116 airports |
| Lands in | `db/seeds/airports.csv` (provenance repeated in the file header), `airport` table via `make seed` |

To refresh: re-download, re-apply the filter, update the header's retrieval date.
The ISO-region → state mapping and the three city back-fills (JRG, TEZ, JSA) are
documented in the seed file header.

## Carriers — loaded, done

Scheduled Indian domestic operators (DGCA operator list; IATA/ICAO designators as
published by the carriers), compiled 2026-09-04 into `db/seeds/carriers.csv`.
`carrier_type` (FSC/LCC/REGIONAL) is APIx's own methodological classification.

## DGCA monthly domestic traffic — loader ready, data NOT loaded

`dgca_pax_share` in `config/basket.yaml` is **null on every route** until a human
supplies one month's real release. The shares are never estimated, and the loader
refuses a partial vector. Nothing in this repository invents a DGCA number.

### What to download

1. Go to the DGCA website (<https://www.dgca.gov.in>) → *Statistics & Reports* →
   **Monthly Statistics of Domestic Passenger Traffic** (the "Domestic Traffic
   Report" workbook for the month you want, published with roughly a one-month lag).
2. From that workbook you need two things:
   * the **city-pair-wise passenger table** for the month, and
   * the headline **total passengers carried by domestic airlines** for the same
     month (used as the share denominator).

Collection basis: OFFICIAL_PUBLICATION. Note that `config/sources.yaml` still lists
`dgca_traffic` as `NOT_REVIEWED`/disabled — automated collection stays off until that
review is recorded; this manual, human-in-the-loop download is the interim path, and
is why the loader takes a file rather than a URL.

### Where to put it

The workbook layout is formatted for human readers and shifts between months, so the
loader takes a small normalised CSV extract you produce from the city-pair table:

```
db/seeds/dgca/2026-07.csv        # name it after the release month
```

```csv
# DGCA Monthly Domestic Traffic Report, July 2026.
# Downloaded 2026-09-10 from <exact URL of the workbook>.
# Extracted by <name> on <date>; passengers are one direction per row.
origin_city,dest_city,passengers
DELHI,MUMBAI,412345
MUMBAI,DELHI,401234
...
```

One row per direction, DGCA's own city spellings are fine (`dgca_loader.CITY_ALIASES`
maps them onto the airports seed: Delhi→New Delhi, Bangalore→Bengaluru, Goa→Vasco da
Gama, …). Keep the `#` header: the file is the audit record of where the numbers
came from. Commas inside numbers are tolerated.

### How to load it

```sh
make load-dgca FILE=db/seeds/dgca/2026-07.csv MONTH=2026-07 TOTAL_PAX=13200000
#                                                           ^ headline total from the same release
```

(or `uv run python -m apix_scheduler.dgca_loader db/seeds/dgca/2026-07.csv
--month 2026-07 --total-domestic-pax 13200000`, with `--dry-run` to preview).

The loader writes `dgca_pax_share = passengers / TOTAL_PAX` for **all 50 routes** into
`config/basket.yaml` (comments preserved, each share annotated with the release
month), re-validates the file against `BasketConfig`, and aborts writing nothing if
any basket route is absent from the extract. After it runs, `make seed` refreshes the
`route` table.

## ATF (aviation turbine fuel) prices — loader ready, data NOT loaded

`atf_price` is empty until a human supplies a real, cited extract. The ATF
pass-through estimate (`apix_core.nowcast.atf_passthrough`) is a pure function that
will fit against whatever `observations` it is handed — including this table's rows,
once loaded — and refuses to fit below `config/nowcast.yaml`'s
`atf_passthrough.min_observations`. Nothing in this repository invents an ATF price.

### What to download

Indian oil marketing companies (IOCL, BPCL, HPCL) publish ATF price notifications,
typically monthly, per city. IOCL's is the most commonly cited benchmark.

Collection basis: OFFICIAL_PUBLICATION. `config/sources.yaml` carries no automated
entry for any oil marketing company's site — none has been reviewed — so this manual
download is the only path today, exactly like the DGCA release above.

### Where to put it, and how to load it

```
db/seeds/atf/2026-09.csv        # name it after the release month
```

```csv
# IOCL ATF price notification, effective 2026-09-01.
# Downloaded 2026-09-10 from <exact URL>. Extracted by <name> on <date>.
price_date,city,price_per_kl
2026-09-01,Delhi,98765.43
2026-09-01,Mumbai,97654.32
```

```sh
make load-atf FILE=db/seeds/atf/2026-09.csv NOTE="IOCL notification, effective 2026-09-01, <url>"
```

(or `uv run python -m apix_scheduler.atf_loader db/seeds/atf/2026-09.csv --source-note "..." --dry-run`).

Insertion is append-only: a later, corrected notification is a new row, never an
overwrite — see `apix_core.models.reference_series.AtfPrice`.

## CPI air-fare item index — loader ready, data NOT loaded

`cpi_airfare_index` is empty until a human supplies a real, cited extract of MoSPI's
published index. The nowcast bridge model
(`apix_core.nowcast.bridge.fit_bridge_model`) needs this series as its target; with
the table empty, `make nowcast-run` logs an honest skip
(`nowcast_run_skipped_no_target_row`/`nowcast_run_skipped`) rather than fabricating a
CPI figure to bridge against.

### What to download

MoSPI publishes the monthly CPI (Rural+Urban) with a sub-group breakdown that
includes "Air fare" under Transport and communication, typically with a roughly
one-month lag.

Collection basis: OFFICIAL_PUBLICATION. No automated collection of MoSPI's release is
reviewed or enabled.

### Where to put it, and how to load it

```
db/seeds/cpi/2026-07.csv
```

```csv
# MoSPI CPI (Rural+Urban), Transport and communication -> Air fare item index.
# Downloaded 2026-09-10 from <exact URL>. Extracted by <name> on <date>.
period,value,base_year,release_date
2026-07,142.3,2011-12,2026-08-12
```

```sh
make load-cpi FILE=db/seeds/cpi/2026-07.csv NOTE="MoSPI release, July 2026, <url>"
```

Insertion is append-only: a later MoSPI revision of a period is a new row with a later
`release_date`, never an overwrite of the earlier vintage — see
`apix_core.models.reference_series.CpiAirfareIndex`.

## DGCA (or other cited benchmark) average fares — loader ready, data NOT loaded

`dgca_fare_reference` is empty. **Provenance caveat, stated plainly**: as verified when
this table was introduced, DGCA's Monthly Domestic Traffic Report — the only DGCA feed
this repository has actually inspected (see the passenger-share section above) —
publishes traffic and capacity, not average fares. This loader and table are ready for
whatever official average-fare benchmark is eventually cited (a future DGCA product, an
AERA tariff filing, or another named official source); until one is cited and loaded,
the back-test harness (`apix_core.backtest.score`, `make backtest`) honestly reports
zero scored periods for every scope — see `docs/backtest.md`.

### Where to put it, and how to load it

```
db/seeds/dgca_fares/2026-07.csv
```

```csv
# <benchmark name> average fare extract for July 2026.
# Downloaded 2026-09-10 from <exact URL>. Extracted by <name> on <date>.
route_code,period,avg_fare
DEL-BOM,2026-07,5432.10
BOM-DEL,2026-07,5310.00
```

```sh
make load-dgca-fares FILE=db/seeds/dgca_fares/2026-07.csv NOTE="<citation>"
```

Every basket route named in the extract must already exist in the `route` table;
the loader aborts writing nothing if any is missing. Insertion is append-only — see
`apix_core.models.reference_series.DgcaFareReference`.

## Rail (AC-2) fares — interface implemented, no source integrated

No automated or manual rail-fare collection exists yet. The comparison this repository
would compute — `apix_core.watchdog.rail.compare_to_rail` — is implemented and tested
against fixtures; `apix_core.watchdog.rail.RailFareSource` is the interface a real feed
would implement, and `NotImplementedRailFareSource` (what runs today) raises a clear
`NotImplementedError` naming this document rather than returning an empty or invented
comparison. `rail_fare` (see `apix_core.models.reference_series.RailFare`) is the
landing table once a source exists — corridor identifiers are mapped from basket routes
via `config/watchdog.yaml`'s `rail.corridor_map`, which is empty today.

Bringing up a real rail-fare source (IRCTC/CRIS or a licensed aggregator) needs the same
review this repository requires of every other source: a `config/sources.yaml` entry
with a recorded `tos_verdict`, before any request through `PolicyEngine` could ever be
issued.

## Synthetic dataset — not an external source

`make seed-synthetic` data comes from `apix_core.testing.synthetic` under
`config/synthetic.yaml`, is tagged `SYNTHETIC` on source_type, collection_method and
legal_basis, and is documented in `fixtures/synthetic/anomaly_ground_truth.json`. It
is listed here only to say: it is generated, labelled, and never a source.
