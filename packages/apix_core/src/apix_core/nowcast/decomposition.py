r"""Movement decomposition: pure price, mix and tax/fee effects that sum exactly.

Every rollup step in :mod:`apix_core.index.aggregate` is a weighted arithmetic mean of
log values (renormalised weights, i.e. shares summing to 1 within each group). For any
such weighted sum :math:`S = \sum_i w_i x_i`, the Bennet (midpoint) decomposition of
its change,

.. math::

    \Delta S = \sum_i \bar w_i \Delta x_i + \sum_i \bar x_i \Delta w_i,
    \quad \bar w = \tfrac{w(t)+w(t-1)}{2},\ \bar x = \tfrac{x(t)+x(t-1)}{2}

is *exact*, not approximate — expanding both sums and cancelling the cross terms
leaves exactly :math:`\sum_i w_i(t)x_i(t) - \sum_i w_i(t-1)x_i(t-1)`, the observed
change, with zero residual (see :func:`bennet_two_factor`).

The real aggregation hierarchy nests three such weighted sums — carrier within
``(route_code, advance_window)`` (weight: ``n_quotes``), ``advance_window`` within
``route_code`` (weight: the booking-profile distribution,
:mod:`apix_core.index.weighting`), and ``route_code`` within the national aggregate
(weight: ``dgca_pax_share``, :mod:`apix_core.index.aggregate`). Substituting the
Bennet identity at each level and telescoping (see the module's ADR / test suite for
the full derivation) gives four additive, non-overlapping terms — pure price,
carrier mix, advance-window mix, route mix — that sum to the change in the *base-fare*
hierarchy exactly. Re-running the identical computation on the total-fare hierarchy and
taking the difference gives a fifth term, ``tax_fee_effect``, so all five sum to the
*observed* (total-fare) change exactly, by construction (composition of two exact
identities, not a fitted or approximate residual).

As of this module's introduction, ``config/method.yaml``'s booking-profile weights and
``config/basket.yaml``'s ``dgca_pax_share`` are period-invariant (stated assumptions,
not time-varying measurements — see those files) — so ``advance_window_mix_effect``
and ``route_mix_effect`` will be exactly zero against the real, shipped config today.
That is the honest, correct answer given what those weights currently are, not a bug in
this module; the ``*_current`` parameters below exist so a future caller with genuinely
time-varying weights (a real booking-profile series, a new DGCA release) needs no
change here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date

    from numpy.typing import NDArray

REQUIRED_ELEMENTARY_COLUMNS = (
    "route_code",
    "advance_window",
    "carrier_iata",
    "n_quotes_prior",
    "n_quotes_current",
    "index_value_prior",
    "index_value_current",
)


def bennet_two_factor(
    weight_prior: NDArray[np.float64],
    weight_current: NDArray[np.float64],
    log_value_prior: NDArray[np.float64],
    log_value_current: NDArray[np.float64],
) -> tuple[float, float]:
    """Exact two-factor ``(price_effect, mix_effect)`` split of one weighted-log-sum's
    change. See the module docstring for the identity this implements.
    """
    w_prior = np.asarray(weight_prior, dtype=np.float64)
    w_current = np.asarray(weight_current, dtype=np.float64)
    x_prior = np.asarray(log_value_prior, dtype=np.float64)
    x_current = np.asarray(log_value_current, dtype=np.float64)
    w_bar = (w_prior + w_current) / 2.0
    x_bar = (x_prior + x_current) / 2.0
    price_effect = float(np.sum(w_bar * (x_current - x_prior)))
    mix_effect = float(np.sum(x_bar * (w_current - w_prior)))
    return price_effect, mix_effect


@dataclass(frozen=True)
class MovementComponents:
    """A period's index movement, split into five components summing to
    ``total_change`` (see :attr:`reconstructed_total`).
    """

    period_from: date
    period_to: date
    total_change: float
    pure_price_effect: float
    route_mix_effect: float
    carrier_mix_effect: float
    advance_window_mix_effect: float
    tax_fee_effect: float

    @property
    def reconstructed_total(self) -> float:
        """Sum of the five components — must equal :attr:`total_change` exactly, to
        floating-point tolerance. This is the identity the required test asserts.
        """
        return (
            self.pure_price_effect
            + self.route_mix_effect
            + self.carrier_mix_effect
            + self.advance_window_mix_effect
            + self.tax_fee_effect
        )


class _HierarchyChange(NamedTuple):
    pure_price_effect: float
    carrier_mix_effect: float
    advance_window_mix_effect: float
    route_mix_effect: float
    total_change: float


def _share(df: pd.DataFrame, weight_col: str, group_cols: list[str]) -> pd.Series:
    if group_cols:
        total = df.groupby(group_cols)[weight_col].transform("sum")
    else:
        total = pd.Series(float(df[weight_col].sum()), index=df.index)
    if (total <= 0).any():
        raise ValueError(f"decompose_movement: a group's {weight_col} sums to zero or less")
    return df[weight_col] / total


def _validate_elementary(df: pd.DataFrame, name: str) -> None:
    missing = [c for c in REQUIRED_ELEMENTARY_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"decompose_movement: {name} missing required columns: {missing}")
    if df.empty:
        raise ValueError(f"decompose_movement: {name} must have at least one row")
    for col in ("index_value_prior", "index_value_current"):
        if (df[col] <= 0).any():
            raise ValueError(f"decompose_movement: {name}.{col} must be strictly positive")
    for col in ("n_quotes_prior", "n_quotes_current"):
        if (df[col] < 0).any():
            raise ValueError(f"decompose_movement: {name}.{col} must be non-negative")


def _hierarchy_change(
    elementary: pd.DataFrame,
    booking_profile_weights_prior: Mapping[str, float],
    booking_profile_weights_current: Mapping[str, float],
    dgca_pax_share_prior: Mapping[str, float],
    dgca_pax_share_current: Mapping[str, float],
) -> _HierarchyChange:
    """The four-term telescoped Bennet decomposition for one fare basis, plus the
    directly-computed total change as an internal cross-check that the telescoping was
    implemented correctly (the two must agree to floating-point tolerance; see the
    assertion at the end).
    """
    df = elementary.copy()
    df["_x_prior"] = np.log(df["index_value_prior"].to_numpy(dtype=np.float64))
    df["_x_current"] = np.log(df["index_value_current"].to_numpy(dtype=np.float64))

    # --- level 1: carrier within (route_code, advance_window), weight = n_quotes ---
    cell_group = ["route_code", "advance_window"]
    df["_s1_prior"] = _share(df, "n_quotes_prior", cell_group)
    df["_s1_current"] = _share(df, "n_quotes_current", cell_group)
    s1_bar = 0.5 * (df["_s1_prior"] + df["_s1_current"])
    x1_bar = 0.5 * (df["_x_prior"] + df["_x_current"])
    df["_price1"] = s1_bar * (df["_x_current"] - df["_x_prior"])
    df["_mix1"] = x1_bar * (df["_s1_current"] - df["_s1_prior"])
    df["_logI1_prior"] = df["_s1_prior"] * df["_x_prior"]
    df["_logI1_current"] = df["_s1_current"] * df["_x_current"]

    cell = df.groupby(cell_group, as_index=False).agg(
        logI_prior=("_logI1_prior", "sum"),
        logI_current=("_logI1_current", "sum"),
        carrier_price_local=("_price1", "sum"),
        carrier_mix_local=("_mix1", "sum"),
    )

    # --- level 2: advance_window within route_code, weight = booking_profile ---
    bp_prior = cell["advance_window"].map(dict(booking_profile_weights_prior))
    bp_current = cell["advance_window"].map(dict(booking_profile_weights_current))
    bp_missing = bp_prior.isna() | bp_current.isna()
    unmatched_windows = sorted(cell.loc[bp_missing, "advance_window"].unique())
    if unmatched_windows:
        raise ValueError(
            f"decompose_movement: no booking-profile weight configured for windows: "
            f"{unmatched_windows}"
        )
    cell = cell.assign(
        _w2_prior=bp_prior.to_numpy(dtype=np.float64),
        _w2_current=bp_current.to_numpy(dtype=np.float64),
    )
    cell["_s2_prior"] = _share(cell, "_w2_prior", ["route_code"])
    cell["_s2_current"] = _share(cell, "_w2_current", ["route_code"])
    s2_bar = 0.5 * (cell["_s2_prior"] + cell["_s2_current"])
    logi2_bar = 0.5 * (cell["logI_prior"] + cell["logI_current"])
    cell["_window_mix_contrib"] = logi2_bar * (cell["_s2_current"] - cell["_s2_prior"])
    cell["_carrier_price_contrib"] = s2_bar * cell["carrier_price_local"]
    cell["_carrier_mix_contrib"] = s2_bar * cell["carrier_mix_local"]
    cell["_logI2_prior"] = cell["_s2_prior"] * cell["logI_prior"]
    cell["_logI2_current"] = cell["_s2_current"] * cell["logI_current"]

    route = cell.groupby("route_code", as_index=False).agg(
        logI_prior=("_logI2_prior", "sum"),
        logI_current=("_logI2_current", "sum"),
        window_mix_local=("_window_mix_contrib", "sum"),
        carrier_price_local=("_carrier_price_contrib", "sum"),
        carrier_mix_local=("_carrier_mix_contrib", "sum"),
    )

    # --- level 3: route_code within national, weight = dgca_pax_share ---
    dp_prior = route["route_code"].map(dict(dgca_pax_share_prior))
    dp_current = route["route_code"].map(dict(dgca_pax_share_current))
    dp_missing = dp_prior.isna() | dp_current.isna()
    unmatched_routes = sorted(route.loc[dp_missing, "route_code"].unique())
    if unmatched_routes:
        raise ValueError(
            f"decompose_movement: no dgca_pax_share weight configured for routes: "
            f"{unmatched_routes}"
        )
    route = route.assign(
        _w3_prior=dp_prior.to_numpy(dtype=np.float64),
        _w3_current=dp_current.to_numpy(dtype=np.float64),
    )
    route["_s3_prior"] = _share(route, "_w3_prior", [])
    route["_s3_current"] = _share(route, "_w3_current", [])
    s3_bar = 0.5 * (route["_s3_prior"] + route["_s3_current"])

    logi3_bar = 0.5 * (route["logI_prior"] + route["logI_current"])
    pure_price_effect = float((s3_bar * route["carrier_price_local"]).sum())
    carrier_mix_effect = float((s3_bar * route["carrier_mix_local"]).sum())
    advance_window_mix_effect = float((s3_bar * route["window_mix_local"]).sum())
    route_mix_effect = float((logi3_bar * (route["_s3_current"] - route["_s3_prior"])).sum())

    national_prior = float((route["_s3_prior"] * route["logI_prior"]).sum())
    national_current = float((route["_s3_current"] * route["logI_current"]).sum())
    total_change = national_current - national_prior

    reconstructed = (
        pure_price_effect + carrier_mix_effect + advance_window_mix_effect + route_mix_effect
    )
    residual = abs(reconstructed - total_change)
    if residual > 1e-6:
        raise AssertionError(
            f"decompose_movement: internal telescoping check failed — components sum to "
            f"{reconstructed} but the directly-computed national change is {total_change} "
            f"(residual {residual}). This indicates a bug in _hierarchy_change."
        )
    return _HierarchyChange(
        pure_price_effect=pure_price_effect,
        carrier_mix_effect=carrier_mix_effect,
        advance_window_mix_effect=advance_window_mix_effect,
        route_mix_effect=route_mix_effect,
        total_change=total_change,
    )


def decompose_movement(
    elementary_total: pd.DataFrame,
    elementary_base: pd.DataFrame,
    booking_profile_weights: Mapping[str, float],
    dgca_pax_share: Mapping[str, float],
    period_from: date,
    period_to: date,
    booking_profile_weights_current: Mapping[str, float] | None = None,
    dgca_pax_share_current: Mapping[str, float] | None = None,
    tolerance: float = 1e-9,
) -> MovementComponents:
    """Decompose the national index's change between ``period_from`` and
    ``period_to`` into five components summing to the observed total change.

    ``elementary_total``/``elementary_base`` carry one row per
    ``(route_code, advance_window, carrier_iata)`` elementary cell, with
    ``n_quotes_prior``/``n_quotes_current`` and ``index_value_prior``/
    ``index_value_current`` — the same identity :mod:`apix_core.index.aggregate`
    consumes, on the total-fare and base-fare bases respectively (re-run whatever
    elementary/multilateral step produced ``elementary_total`` a second time against
    ``base_fare`` in place of ``total_fare`` to get ``elementary_base`` — no new
    aggregation code, the existing index maths applied to a different column).

    ``booking_profile_weights``/``dgca_pax_share`` are the weights the real index
    uses (``config/method.yaml``, ``config/basket.yaml``); ``*_current`` overrides
    let a caller with genuinely time-varying weights supply the current period's
    values separately (both default to the same, period-invariant dict, matching
    those config files' present, stated-assumption reality — see the module
    docstring).

    Raises :class:`ValueError` on missing columns, non-positive index values, or a
    route/window with no configured weight. Raises :class:`AssertionError` if the
    five components fail to sum to ``total_change`` within ``tolerance`` — this would
    indicate a bug in this function, not a real data condition, since the
    decomposition is exact by construction.
    """
    _validate_elementary(elementary_total, "elementary_total")
    _validate_elementary(elementary_base, "elementary_base")
    bp_current = booking_profile_weights_current or booking_profile_weights
    dp_current = dgca_pax_share_current or dgca_pax_share

    total_hierarchy = _hierarchy_change(
        elementary_total, booking_profile_weights, bp_current, dgca_pax_share, dp_current
    )
    base_hierarchy = _hierarchy_change(
        elementary_base, booking_profile_weights, bp_current, dgca_pax_share, dp_current
    )

    tax_fee_effect = total_hierarchy.total_change - base_hierarchy.total_change
    components = MovementComponents(
        period_from=period_from,
        period_to=period_to,
        total_change=total_hierarchy.total_change,
        pure_price_effect=base_hierarchy.pure_price_effect,
        route_mix_effect=base_hierarchy.route_mix_effect,
        carrier_mix_effect=base_hierarchy.carrier_mix_effect,
        advance_window_mix_effect=base_hierarchy.advance_window_mix_effect,
        tax_fee_effect=tax_fee_effect,
    )
    residual = abs(components.reconstructed_total - components.total_change)
    if residual > tolerance:
        raise AssertionError(
            f"decompose_movement: components sum to {components.reconstructed_total} but "
            f"total_change is {components.total_change} (residual {residual} exceeds "
            f"tolerance {tolerance})"
        )
    return components


__all__ = [
    "REQUIRED_ELEMENTARY_COLUMNS",
    "MovementComponents",
    "bennet_two_factor",
    "decompose_movement",
]
