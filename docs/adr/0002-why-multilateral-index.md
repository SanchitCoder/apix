# 2. Use a multilateral index method, not a bilateral chained one

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** APIx engineering
- **Method config:** `config/method.yaml` (`multilateral_method: geks_tornqvist`)

## Context

The natural first instinct for a price index is a bilateral chained one: compare this
month's prices with last month's for the products present in both, chain the resulting
links together, and publish the running product. It is what a chained Laspeyres or a
chained Jevons does, and it is what most people picture when they hear "price index".

Airfares break it.

**The product set churns violently.** A "product" here is something like *DEL-BOM,
IndiGo, 07:15 departure, non-stop, 14 days ahead, economy*. Between one month and the
next, schedules change, flight numbers are retimed, routes are added and dropped, and
fare brands are renamed. The overlap between consecutive months is partial and the
non-overlapping part is not random — it is concentrated in exactly the itineraries whose
prices moved most.

**Chain drift.** When the matched sample changes composition every period, the chained
product of period-on-period links diverges from a direct comparison between the endpoints.
The error compounds: it does not average out, it accumulates in one direction. For
high-frequency, high-churn data this is not a rounding concern. Published work on
scanner data — where the same churn problem appears — has found chained bilateral indices
drifting by tens of percentage points over a few years. Airfares churn faster than
groceries.

**Prices are strongly non-stationary in a way that interacts badly with chaining.** A
fare is a function of how far ahead it is observed. Comparing a 14-day-out fare in one
month against a 14-day-out fare in the next is fine; comparing whatever happened to be
available is not. Any method must hold the advance-purchase window fixed, which shrinks
the matched sample further and makes the churn problem worse.

**The audience matters.** MoSPI and the RBI will not accept "the index drifted because of
sample churn" as an explanation for a Transport sub-group movement. The method has to be
defensible against a specific, well-known criticism.

## Decision

We compute the index using a **multilateral method over a rolling window**: GEKS-Törnqvist
over a 13-month window, spliced on the movement.

**Multilateral.** Every period in the window is compared with every other period, and the
results are reconciled into a single set of index levels. Every bilateral comparison
contributes, not only the adjacent ones, so a product missing from one month still
informs the comparisons between the months it does appear in. The result is transitive by
construction: the comparison from January to June is the same whether taken directly or
through the intervening months. Transitivity is the property chaining lacks, and it is
precisely the property that eliminates chain drift.

**GEKS-Törnqvist specifically.** Törnqvist is a superlative index — it corresponds to a
flexible underlying preference structure rather than assuming fixed quantities — and GEKS
is the standard way to make a set of superlative bilateral comparisons transitive. The
combination is what statistical agencies have converged on for high-churn data, which
matters: adopting the method other agencies already defend is cheaper than defending a
novel one.

**13-month window.** Long enough to contain a full seasonal cycle plus the comparison
month, so a route that only operates in one season still enters the estimation. Longer
windows dilute the influence of recent periods and increase the computation cost, which
for a monthly published series buys nothing.

**Movement splice.** When the window rolls forward, the published series is extended by
the most recent period-on-period movement from the new window rather than by re-levelling
the whole series. This keeps already-published figures unrevised at the splice point.
Alternatives (window, half, mean splice) are in `SpliceMethod` and can be computed for
comparison; movement splice is chosen because a national statistics office needs the
published back-series to be stable, and a splice that revises history at every window roll
is not publishable.

**Elementary aggregates below the weights use Jevons** — the geometric mean of price
relatives. It passes the time-reversal test and is the standard choice for a stratum
without quantity information. Carli is present in the enum for comparison but
`MethodConfigFile` rejects it as the published formula: it is upward-biased and fails
time reversal, and a reviewer would reject the series on that basis alone.

## Consequences

**Good.**

- No chain drift. The index between any two periods in a window is the same regardless of
  the path taken.
- Products present in only some periods still contribute, which is most of them.
- The method is one MoSPI and the RBI already recognise from the international literature,
  so the conversation is about our data rather than about our arithmetic.

**Costly.**

- Considerably more computation: an all-pairs comparison over 13 periods, re-estimated
  each month, against every stratum. This is why `apix_core/index/` is specified as pure
  functions over dataframes — it has to be optimisable and testable in isolation.
- Harder to explain. A journalist can follow a chained Laspeyres; GEKS-Törnqvist needs a
  paragraph. `docs/methodology.md` has to carry that paragraph.
- The window length and the splice method are now published methodological parameters. A
  change to either changes the number, which is why both live in `config/method.yaml`, the
  file is hashed, and the hash is stamped onto every `index_run`.
- Revisions become a first-class concern rather than an afterthought. `index_value` is
  keyed by `(index_run_id, series_id, period)` so that a recomputation is a new row rather
  than an overwrite, and `revision_log` records every change to an already-published
  number. That schema shape is a direct consequence of this decision.

**Deferred.**

- The choice between GEKS-Törnqvist and the Time Product Dummy is not finally settled.
  TPD handles very sparse strata better and folds the hedonic quality adjustment into the
  same regression. Both are in `MultilateralMethod`. Phase 3 will compute both against the
  synthetic dataset and against the first real collection window, and a follow-up ADR will
  record the outcome. This ADR commits to *multilateral*; the specific estimator remains
  open.
- Quality adjustment is specified as a time-dummy hedonic over
  `advance_days`, `dep_hour_bucket`, `stops` and `carrier_iata`. Refundability and baggage
  allowance are collected and are strong price determinants, but are not yet columns on
  `fare_quote_clean`. Promoting them is a Phase 2 migration and a follow-up ADR.
