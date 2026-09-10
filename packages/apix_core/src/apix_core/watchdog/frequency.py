"""The personalised-pricing probe's "low frequency" runtime gate.

Enforced twice: schema-level (``config/watchdog.yaml``'s
``personalisation_probe.max_runs_per_day`` has a hard ceiling — see
:mod:`apix_core.config.watchdog`) and here, at runtime, before a probe is allowed to
start — on top of, not instead of, the per-source Redis rate limiter every individual
request already passes through inside :class:`apix_core.policy.engine.PolicyEngine`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


def can_run_probe_now(
    last_run_at: datetime | None, min_interval_hours: float, now: datetime
) -> bool:
    """Whether enough time has passed since ``last_run_at`` to start another probe.

    ``last_run_at=None`` (no prior run recorded) always permits a run — the honest
    reading of "never run before", not a reason to refuse.
    """
    if last_run_at is None:
        return True
    elapsed_hours = (now - last_run_at).total_seconds() / 3600.0
    return elapsed_hours >= min_interval_hours


__all__ = ["can_run_probe_now"]
