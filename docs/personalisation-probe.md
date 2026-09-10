# The personalised-pricing probe

This document describes the method implemented in `apix_core.watchdog.dispersion` and
`apix_collector.personalisation.probe`. It is maintained by hand, like
`docs/imputation.md`, because it explains *why* and *with what limitations*, not a
config file's contents.

## What the probe does

For a configured `(source, route)`, the probe issues the identical search query
through N session profiles at as close to the same instant as the collection path
allows, and measures how much the returned fare differs across them.

Each profile varies three axes, drawn from `config/watchdog.yaml`'s
`personalisation_probe` section (`apix_core.config.watchdog.PersonalisationProbeConfig`):

* **cookie state** — `none`, `existing_thin` (a synthetic marker for one prior visit),
  `existing_thick` (several). A real profile's actual cookie jar is never captured or
  replayed; these are synthetic markers set on the outgoing request, never derived from
  a real user's session.
* **UA class** — `desktop_chrome`, `mobile_safari`, and similar: distinct `User-Agent`
  strings, not a claim of full device/browser fingerprinting.
* **geography** — an `Accept-Language` header tag (e.g. `in_delhi`, `in_mumbai`). This
  is **honestly a header-only simulation**, not real geo-IP proxying. Real proxy egress
  is explicitly out of scope for `apix_collector` today (see
  `apix_collector.session`'s own module docstring) — the probe does not pretend
  otherwise.

Every request goes through exactly the same path every other APIx collection request
does: `apix_collector.run.run_spider_once`, gated by the source's own `PolicyEngine`.
Nothing about the probe bypasses rate limits, robots rules, or the ToS-verdict check —
it is a different *pattern* of otherwise-ordinary requests, not a different compliance
regime.

## What "low frequency" means, concretely

Personalisation probing is a heavier footprint than ordinary collection: N
near-simultaneous requests for one flight, issued specifically to compare, not just to
observe. `config/watchdog.yaml` enforces low frequency twice:

1. **Schema-level ceiling** — `PersonalisationProbeConfig.max_runs_per_day` cannot
   exceed 6 (`apix_core.config.watchdog._MAX_RUNS_PER_DAY_CEILING`), and the schema
   itself rejects a `max_runs_per_day` / `min_interval_hours` combination that would
   not fit in a 24-hour day.
2. **Runtime gate** — `apix_core.watchdog.frequency.can_run_probe_now` is checked
   before `apix_scheduler.watchdog_run probe` does anything at all, based on the most
   recent `personalisation_probe_observation.probed_at` in the database.

Both sit on top of, not instead of, the ordinary per-source Redis rate limiter every
individual request already passes through inside `PolicyEngine`.

## The dispersion statistic

`apix_core.watchdog.dispersion.compute_dispersion` reports, per
`(source_code, flight_key, probed_at)` probe instance: the coefficient of variation
(population standard deviation over the mean) of the N sessions' `total_fare`, plus
`min_fare`/`max_fare`/`n_sessions` for context. A single-session probe instance has a
defined dispersion of exactly `0.0` — there is nothing to disperse, which is a real
answer, not a missing one.

## Limitations — read before treating a nonzero statistic as evidence of anything

**A nonzero dispersion statistic is not proof of personalised pricing.** Plausible,
entirely innocent explanations include:

* **Cache staleness** — one session's request may hit a cached response a few seconds
  older than another's, and fares move on their own between those seconds regardless
  of who is asking.
* **Inventory / seat-map movement** — a fare bucket can close between two
  near-simultaneous requests simply because another traveller (anywhere, unrelated to
  this probe) booked the last seat in it. This looks identical to a session-dependent
  price without being one.
* **Promo or session-scoped pricing that is not personalisation** — a source may run a
  site-wide flash sale keyed to a session token or timestamp for reasons that have
  nothing to do with who is asking (e.g. an anti-scraping cache-buster, a random A/B
  test bucket assigned per session rather than per person).
* **Retry/backoff timing** — `apix_collector.spiders.base.BaseSpider`'s retry logic can
  introduce a real, if small, time gap between two profiles' requests, during which any
  of the above can happen.

The probe measures **dispersion**, a fact about what N sessions observed. It does not,
and cannot on its own, establish **cause**. Treat a sustained, repeated, direction-
consistent dispersion pattern across many probe runs as worth investigating further —
not a single instance as a finding.

## What never happens

* The probe never re-identifies, targets, or replays a real user's session. Every
  "cookie state" is a synthetic marker chosen from a small fixed vocabulary
  (`config/watchdog.yaml`), never a captured real cookie.
* The probe is never used to price-discriminate back against a source, request a
  discount, or otherwise act on what it observes beyond recording it.
* The probe runs only at the configured low frequency (above) — it is never triggered
  ad hoc outside `apix_scheduler.watchdog_run probe`'s own gate.
* `apix_core.watchdog.dispersion` never infers or reports a cause. It reports a number
  and how many sessions it rests on; the "what this might mean" judgement belongs to a
  human reading this document, not to the code.

## Today's honest baseline

The only enabled source in this repository is `fixture_replay` (a static recorded
response — see `config/sources.yaml`). Every session profile probing it receives an
identical fare, so a probe run today correctly reports dispersion `0.0` for every
instance. That is not a limitation of the probe's logic — it is the correct answer for
a source whose response genuinely does not vary by session. The probe is real
end-to-end (config, N-profile collection, persistence, the dispersion statistic) and
would detect real dispersion the moment it runs against a source whose fares actually
depend on who is asking.
