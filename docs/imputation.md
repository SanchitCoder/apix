# Missing-value and sell-out handling

This document describes the rules implemented in `apix_core.clean.missing`. It is
maintained by hand (unlike `docs/methodology.md`, which is generated) because it
explains *why* the pipeline treats gaps the way it does, not a config file's contents.

## Three reasons a cell can be empty

An index run is defined over an **expected sampling grid**: for every
`(source, route, carrier, flight_number, advance_days, query_date, travel_date)` cell
the collector is supposed to probe, there should be a row in `fare_quote`. When one is
missing, there are exactly three possible reasons, and the pipeline treats each
differently. Conflating them — as a naive "fill the gap somehow" approach would — either
hides a compliance/collection problem behind manufactured data, or throws away a
genuine, informative absence (a sell-out is a price signal in its own right: demand was
high enough to close every fare bucket).

### 1. Not collected (source blocked)

The collector never got an answer for this cell — the source was blocked by policy, the
run failed, or no run was ever attempted. There is no evidence about the price, positive
or negative.

**Treatment:** left as a gap. No imputation is attempted. It reduces `coverage_pct` for
its `(route_id, advance_days)` cell, and a coverage figure that falls below
`config/cleaning.yaml`'s `quality_gates.coverage_floor_pct` blocks the index run outright
(see `apix_core.clean.gates`).

**Detected by:** `apix_core.clean.missing.classify_missing_cells` looks up the
`collection_run` outcome for the cell's `(source_id, route_id, query_date)`. Anything
other than `SUCCEEDED` or `PARTIAL` — `BLOCKED`, `FAILED`, `PENDING`, `RUNNING`, or no run
record at all — is treated as "no evidence the cell was ever genuinely probed", which is
the conservative reading: absence of proof of a successful attempt is not proof of a
sell-out.

### 2. Collected, no availability (genuine sell-out)

The collector ran successfully and found nothing to quote — every fare bucket on that
flight was closed. This is real information: it means demand was high enough to sell out
the flight, which is itself price-relevant even though no price was displayed.

**Treatment:** imputed by the **cell mean** — the mean `total_fare` of clean,
non-outlier observations sharing the same `(route_id, advance_days, carrier_type)` — and
the imputed row is written with `is_imputed = True` and
`imputation_method = "cell_mean"`. The mean deliberately excludes flagged outliers (a
single anomalous price must never pull the value used to fill a gap) and deliberately
uses `carrier_type` rather than the specific carrier: a sold-out IndiGo flight is
represented by what other LCC flights on the same route and advance-purchase window are
charging, not by an unrelated full-service carrier's price level.

If the `(route_id, advance_days, carrier_type)` group itself has fewer than
`config/cleaning.yaml`'s `imputation.min_group_size` clean observations, there is not
enough evidence to support a mean. The cell is returned as **unresolved** rather than
imputed from too little data — this is the same "never guess silently" rule as
everywhere else in APIx, just applied to imputation specifically.

**Detected by:** the same `classify_missing_cells` lookup — a `SUCCEEDED`/`PARTIAL` run
whose expected cell still has no observed row. **Imputed by:**
`apix_core.clean.missing.impute_sold_out`.

### 3. Collected, malformed

A row exists in `fare_quote` — the collector got a response and parsed something out of
it — but the result fails a basic sanity check: `total_fare` is null, non-positive or
non-finite, or a required identity dimension (`route_id`, `carrier_iata`, `travel_date`,
`advance_days`) is null. This is a parsing or scraping defect, not a price signal.

**Treatment:** quarantined. The row is removed from the analytical pipeline but never
silently dropped — it is returned separately, tagged with `quarantine_reason`
(`"missing_identity_dimension"` or `"invalid_total_fare"`), for inspection. Nothing is
repaired automatically: a malformed row might be salvageable by a human or a collector
fix, but the cleaning pipeline itself never guesses at what it should have said.

**Detected by:** `apix_core.clean.missing.quarantine_malformed`, run before every other
stage — a malformed row must not be allowed to enter deduplication, decomposition or
outlier screening and distort a group it does not belong in.

## What never happens

* A stale price is never carried forward to fill a gap. There is no forward-fill
  anywhere in this pipeline. A cell that cannot be classified as a genuine sell-out with
  enough supporting evidence stays a gap.
* An imputed row's `base_fare` is left null, not back-filled from the imputed
  `total_fare`. Imputation reconstructs a plausible *total*; it does not fabricate a
  base/tax/UDF split that was never observed for that cell.
* An imputed row's `dep_hour_bucket` and `stops` are left null by
  `apix_core.clean.pipeline.clean_quotes`, even though `fare_quote_clean` declares
  `dep_hour_bucket` `NOT NULL`. A caller persisting the pipeline's output is responsible
  for backfilling both from the flight's known schedule (keyed by
  `carrier_iata`/`flight_number`) before insert — the cleaning pipeline has no schedule
  reference to draw on and will not guess a departure hour to satisfy a column
  constraint.

## Coverage accounting

`apix_core.clean.missing.compute_coverage` reports, per `(route_id, advance_days)`:
`expected_count`, `observed_count`, `not_collected_count`, `sold_out_count`,
`imputed_count` and `coverage_pct`. `coverage_pct` is deliberately
`observed_count / expected_count` — it counts only rows that were actually collected.
An imputed sell-out is real, useful data for the *cleaning* output (the index maths can
use it), but it is not evidence that was collected, so it is not allowed to inflate the
coverage figure that the quality gate checks. This is distinct from — and stricter than —
`config/method.yaml`'s `min_coverage_pct`, which governs whether a cell's *index value*
is published, not whether the input data underneath it is trustworthy enough to run at
all.
