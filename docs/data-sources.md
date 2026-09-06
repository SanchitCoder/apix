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

## Synthetic dataset — not an external source

`make seed-synthetic` data comes from `apix_core.testing.synthetic` under
`config/synthetic.yaml`, is tagged `SYNTHETIC` on source_type, collection_method and
legal_basis, and is documented in `fixtures/synthetic/anomaly_ground_truth.json`. It
is listed here only to say: it is generated, labelled, and never a source.
