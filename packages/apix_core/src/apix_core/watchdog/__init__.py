"""Market-integrity watchdog: personalised-pricing dispersion, surge detection,
sell-out velocity, and rail-fare substitution.

Every function here is pure — DataFrames in, DataFrames out, no database access, no
I/O — exactly like :mod:`apix_core.index`. The personalised-pricing probe's actual
egress (issuing N session queries through ``PolicyEngine.request()``) lives in
``apix_collector``, never here — ``tests/test_egress_only.py`` enforces that no module
under this package imports an HTTP client.
"""

from __future__ import annotations

from apix_core.watchdog.dispersion import STATISTIC_NAME, compute_dispersion
from apix_core.watchdog.frequency import can_run_probe_now
from apix_core.watchdog.rail import NotImplementedRailFareSource, RailFareSource, compare_to_rail
from apix_core.watchdog.sellout import compute_sellout_velocity
from apix_core.watchdog.surge import detect_surges

__all__ = [
    "STATISTIC_NAME",
    "NotImplementedRailFareSource",
    "RailFareSource",
    "can_run_probe_now",
    "compare_to_rail",
    "compute_dispersion",
    "compute_sellout_velocity",
    "detect_surges",
]
