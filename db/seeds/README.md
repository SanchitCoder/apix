# Reference seed data

Real, published reference data only. Nothing in this directory is synthetic.

| File | Source | Notes |
|---|---|---|
| `airports.csv` | OurAirports open dataset (public domain / CC0), retrieved 2026-09-04 | All 116 Indian airports with scheduled commercial service and an IATA code. Full provenance (URL, retrieval date, filter, corrections) is in the file's own `#` header. |
| `carriers.csv` | DGCA scheduled domestic operator list, compiled 2026-09-04 | Carriers operating scheduled Indian domestic services. `carrier_type` is APIx's own FSC/LCC/REGIONAL classification and is a methodological choice, documented in `docs/methodology.md`. |

Loaders (`apix_core.seeding`) treat lines starting with `#` as comments, so each
file carries its provenance in its own header.

Routes are **not** seeded from a CSV. They are derived from `config/basket.yaml`, so the
basket has exactly one definition. `dgca_pax_share` is null until the DGCA monthly
domestic traffic release is loaded by `apix_scheduler.dgca_loader` — see
`docs/data-sources.md`. It is never estimated to make a run succeed.
