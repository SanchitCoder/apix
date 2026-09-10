# SDMX-JSON 2.0 — `/v1/sdmx/data/{flow_ref}/{key}`

What this endpoint speaks, why it is shaped the way it is, and what a real MoSPI
eSankhyiki integration would need to check against.

## Status: modelled on general SDMX 2.0 conventions, not confirmed against MoSPI

I could not find a published Data Structure Definition (DSD) for MoSPI's eSankhyiki
CPI series in a form this repository could verify — their public documentation
describes parameter-based access (base year, group/item level) rather than an
SDMX registry endpoint. Rather than invent MoSPI-specific codes and present them as
confirmed, this DSD follows the general SDMX 2.0 conventions used across national
statistics offices publishing CPI-family series (dimensions ordered from coarse to
fine, a time dimension on the observation axis, standard `OBS_STATUS`/`UNIT_MEASURE`
attributes). Mapping this onto MoSPI's actual system, when that access is confirmed,
should be a renaming exercise against the tables below, not a rebuild — that is the
design goal principle 1 (traceability) and the task's own framing ask for, and it is
what this document exists to make checkable.

## Dataflow

| | |
|---|---|
| Agency ID | `IN_APIX` |
| Dataflow ID | `DF_AIRFARE_INDEX` |
| Version | `1.0.0` |
| Flow ref (path segment) | `IN_APIX,DF_AIRFARE_INDEX,1.0.0` |
| Media type | `application/vnd.sdmx.data+json;version=2.0.0` |

## Data Structure Definition

### Dimensions (series key, in key order)

| Position | ID | Codelist | Example values |
|---|---|---|---|
| 0 | `FREQ` | `CL_FREQ` | `M` (monthly — the only frequency APIx publishes today) |
| 1 | `ROUTE` | `CL_ROUTE` | `ALL` (national), or a basket route code, e.g. `DEL-BOM` |
| 2 | `CARRIER_TYPE` | `CL_CARRIER_TYPE` | `ALL`, `FSC`, `LCC`, `REGIONAL` |
| 3 | `AP_WINDOW` | `CL_AP_WINDOW` | `ALL`, or an advance-purchase window code from `config/basket.yaml` (e.g. `AP08_14`) |

A series key is the four values dot-separated, e.g. `M.DEL-BOM.ALL.ALL` for the
DEL-BOM route index, or `M.ALL.ALL.ALL` for the headline national series.

**Resolution rule** (`apix_api/routers/sdmx.py:_series_code_for_key`): the first
non-`ALL` dimension, checked in key order (`ROUTE` before `CARRIER_TYPE` before
`AP_WINDOW`), selects which APIx series answers the request. APIx does not today
publish the finer cross-cuts a key naming more than one non-`ALL` dimension would
imply (a specific route's carrier-type breakdown, say) — that is a real gap, not a
silent approximation: the response is the nearest series APIx actually has, and the
one non-`ALL` dimension that was honoured is exactly the one the resolution rule used.

### Observation dimension

| ID | Role | Values |
|---|---|---|
| `TIME_PERIOD` | `time` | Monthly periods, `YYYY-MM`, one per published `index_value.period` |

### Attributes

| Level | ID | Meaning |
|---|---|---|
| Series | `UNIT_MEASURE` | Always `IX` — index, reference period = 100 (`config/method.yaml: index_reference_value`) |
| Observation | `OBS_STATUS` | `A` (Normal — from a released `index_run`) or `P` (Provisional — a draft run, only ever returned to a researcher/official caller; see the auth section of the main API description) |
| Observation | `N_QUOTES` | The cleaned quote count behind that observation (`index_value.n_quotes`) — SDMX has no standard code for this, so it travels as a plain attribute rather than being dropped at the SDMX boundary (principle 1) |

### What `ALL` means, concretely

* `ROUTE=ALL, CARRIER_TYPE=ALL, AP_WINDOW=ALL` → the headline series, `APIX.ALL.M`.
  **Honestly unpublishable against the shipped `config/basket.yaml`** until DGCA
  passenger-share weights are loaded (every route's `dgca_pax_share` is null today —
  see `docs/data-sources.md`); a request for this key 404s with that as the reason,
  not a fabricated equal-weighted stand-in.
* `ROUTE=<code>` → `APIX.ROUTE.<code>.M`.
* `CARRIER_TYPE=<FSC|LCC|REGIONAL>` (with `ROUTE=ALL`) → `APIX.CARRIERTYPE.<type>.M`.
* `AP_WINDOW=<code>` (with `ROUTE=ALL`, `CARRIER_TYPE=ALL`) → `APIX.WINDOW.<code>.M`.

## Example request/response shape

```
GET /v1/sdmx/data/IN_APIX,DF_AIRFARE_INDEX,1.0.0/M.DEL-BOM.ALL.ALL
```

Returns one SDMX-JSON 2.0.0 data message: `meta` (schema URL, sender, the resolved
series code under the non-standard `apix` key for debugging), and `data.dataSets[0]`
holding one series (`"0:0:0:0"`) whose `observations` map an integer index to
`[value, OBS_STATUS index, N_QUOTES index]`, with the corresponding code lists filled
in under `data.structures[0]`.

## Mapping checklist for a real MoSPI integration

1. Confirm MoSPI's actual dimension order and codelist IDs for its own airfare/
   transport CPI sub-index (if published via SDMX at all) and reconcile against the
   table above — this is expected to be a renaming exercise, per the design goal.
2. Confirm whether MoSPI expects `FREQ` first in the key (as here) or elsewhere in
   its DSD; SDMX does not mandate a universal order, only that a DSD fixes one.
3. Decide how APIx's `ROUTE`/`CARRIER_TYPE`/`AP_WINDOW` breakdowns map onto whatever
   COICOP-style classification (if any) MoSPI uses for the Transport sub-group —
   these are APIx's own methodological dimensions, not necessarily MoSPI's.
4. Confirm MoSPI's `OBS_STATUS` codelist values; `A`/`P` here are the common SDMX
   defaults (Normal/Provisional), not verified against a MoSPI-specific codelist.
