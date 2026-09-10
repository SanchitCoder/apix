"""Bridge model, ATF pass-through and movement decomposition.

Every function here is pure — DataFrames/arrays in, DataFrames/results out, no
database access, no I/O — exactly like :mod:`apix_core.index`. Output of the bridge
model lands in ``nowcast_value`` (:class:`apix_core.models.nowcast.NowcastValue`) and
is never written to ``index_value``: a modelled estimate of a period that is not yet
closed must never be mistakable for a published index number.
"""

from __future__ import annotations

from apix_core.nowcast.atf_passthrough import (
    DistributedLagResult,
    fit_atf_passthrough,
    lag_chart_data,
)
from apix_core.nowcast.atf_passthrough import (
    InsufficientHistoryError as AtfInsufficientHistoryError,
)
from apix_core.nowcast.atf_passthrough import (
    build_design_matrix as build_atf_design_matrix,
)
from apix_core.nowcast.bridge import (
    BridgeModelResult,
    CoefficientEstimate,
    fit_bridge_model,
)
from apix_core.nowcast.bridge import (
    InsufficientHistoryError as BridgeInsufficientHistoryError,
)
from apix_core.nowcast.bridge import (
    build_design_matrix as build_bridge_design_matrix,
)
from apix_core.nowcast.decomposition import (
    MovementComponents,
    bennet_two_factor,
    decompose_movement,
)
from apix_core.nowcast.vintage import VintageViolationError, assert_no_look_ahead, filter_as_of

__all__ = [
    "AtfInsufficientHistoryError",
    "BridgeInsufficientHistoryError",
    "BridgeModelResult",
    "CoefficientEstimate",
    "DistributedLagResult",
    "MovementComponents",
    "VintageViolationError",
    "assert_no_look_ahead",
    "bennet_two_factor",
    "build_atf_design_matrix",
    "build_bridge_design_matrix",
    "decompose_movement",
    "filter_as_of",
    "fit_atf_passthrough",
    "fit_bridge_model",
    "lag_chart_data",
]
