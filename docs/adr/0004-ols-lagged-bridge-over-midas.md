# 4. Nowcast the CPI air-fare item index with an aggregated-regressor OLS, not MIDAS

- **Status:** Accepted
- **Date:** 2026-09-08
- **Deciders:** APIx engineering
- **Method config:** `config/nowcast.yaml` (`bridge_model.kind: ols_lagged`)

## Context

APIx exists to augment the Transport sub-group of the CPI. Doing that in practice
means bridging a daily/near-real-time APIx figure to the monthly, lagged, official CPI
air-fare item index — a nowcast, not a substitute for the official number, and the
task that prompted this ADR asks for exactly that: a bridge model reporting
coefficients, standard errors and diagnostics, with a point estimate and a prediction
interval.

The textbook tool for bridging a high-frequency indicator to a low-frequency target is
MIDAS (Mixed-Data Sampling) regression: it lets the daily APIx path *within* a month
enter the regression with its own estimated within-month weighting, rather than being
collapsed to a single number before the regression ever sees it. Done properly, MIDAS
is the more information-preserving choice.

Two things stood in the way of doing it properly, now:

**No mixed-frequency scaffolding exists in this repository.** `apix_core.index`
publishes at (at most) daily/window granularity from a rolling multilateral estimate;
there is no existing machinery for expressing "the daily path within a not-yet-closed
month" as a structured regressor set (Almon/exponential Almon weighting functions,
their own hyperparameters, the numerical optimisation MIDAS needs to fit them). Building
that scaffolding well is its own project, not a subtask of the nowcast bridge.

**No real CPI air-fare series is loaded yet.** As of this ADR, `cpi_airfare_index` is
empty (see `docs/data-sources.md`) — there is no real target series to validate a MIDAS
specification against, only the fixture/synthetic data this repository is careful never
to treat as if it were real. Committing to MIDAS's added complexity before there is real
data to check it against would be optimising a model nobody can yet evaluate.

## Decision

Phase 1 nowcasts with a **simple aggregated-regressor OLS with lags**:

```
Δln CPI_t = α + Σ_{l=0}^{L_x} β_l · Δln APIx_{t-l} + Σ_{l=1}^{L_y} γ_l · Δln CPI_{t-l} + ε_t
```

`APIx_{t-l}` for closed months is the published headline `index_value` for that
calendar month; `APIx_t` (lag 0, the "aggregated regressor" that gives this approach
its name) is whatever `apix_scheduler.index_run.compute_and_persist` published for the
current, not-yet-closed month as of the nowcast date — a single collapsed number, not a
MIDAS-weighted daily path. `apix_core.nowcast.bridge.fit_bridge_model` fits this by
OLS with HAC-robust standard errors (monthly macro data is routinely serially
correlated), reports the full coefficient table plus R², adjusted R², residual standard
error, Durbin-Watson and Jarque-Bera, and produces an observation-level prediction
interval via `statsmodels`' `get_prediction`.

`BridgeModelKind.MIDAS` is present in `apix_core.config.nowcast`'s enum specifically to
state this growth path in the schema itself, not to hide it: a config author can select
`kind: midas` today, and `fit_bridge_model` raises `NotImplementedError` naming this ADR
— an honest refusal, never a silent fallback to OLS.

Vintage discipline (`apix_core.nowcast.vintage`) applies identically regardless of
which bridge model kind is eventually fit — the look-ahead guard is a property of the
data pipeline, not of the regression specification.

## Consequences

**Good.**

- No new dependency: `statsmodels`, already pinned, is sufficient.
- Every coefficient is directly interpretable (a one-period Δln APIx move's estimated
  effect on Δln CPI at a given lag) — easy to audit, easy to explain in
  `docs/methodology.md` when this model starts feeding it.
- The look-ahead test and the rest of the vintage-safety machinery are exercised fully
  by this specification; nothing about them is MIDAS-specific, so none of that work is
  wasted when MIDAS is eventually built.

**Costly.**

- Cruder within-month weighting than a true MIDAS specification: the current month's
  contribution is one collapsed number, not a path with its own estimated shape. A
  MIDAS bridge would likely extract more signal from a partial month, especially early
  in the month when the collapsed number rests on little data.
- `min_observations` in `config/nowcast.yaml` has to stay conservative (24, two years of
  monthly history) precisely because a monthly-frequency OLS burns degrees of freedom
  fast with lags on both sides; a well-specified MIDAS model can sometimes do more with
  less by exploiting the daily path directly.

**Deferred.**

- MIDAS remains the stated target for a later phase, once (a) real `cpi_airfare_index`
  data is loaded and there is something to validate a mixed-frequency specification
  against, and (b) the daily/partial-month APIx path is itself exposed as a structured
  time series rather than a single collapsed number per nowcast run. A follow-up ADR
  will record the outcome when that work starts, the same way ADR 0002 left the
  GEKS-Törnqvist vs. Time Product Dummy choice explicitly open for Phase 3.
- The ATF pass-through estimate (`apix_core.nowcast.atf_passthrough`) is a plain
  distributed-lag OLS for the same reasons; it is not a candidate for MIDAS since both
  sides of that regression are already monthly.
