"""The labelled synthetic fare generator.

Produces a dataset with the statistical properties of real Indian domestic airfares —
distance-and-carrier price levels, a parameterised advance-purchase curve, weekly and
festival seasonality, bucket sell-outs that leave genuinely missing observations, the
base + tax + UDF + convenience-fee component structure — plus deliberately injected
anomalies recorded in a ground-truth table so detection can be *asserted*, not hoped.

Everything is a pure function of ``(SyntheticConfig, BasketConfig, coordinates, start
date, day count)``: same inputs, byte-identical output. No I/O, no database, no clock
reads. Persistence lives in :mod:`apix_core.testing.seed`.

Nothing generated here is an observation. The seeder tags every row SYNTHETIC on
source_type, collection_method and legal_basis, and every quote id is a uuid5 under
:data:`SYNTHETIC_UUID_NAMESPACE`, so even a stray row remains attributable.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from apix_core.config.synthetic import AnomalyKind

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from numpy.typing import NDArray

    from apix_core.config.basket import BasketConfig
    from apix_core.config.synthetic import SyntheticConfig

# All synthetic quote ids are uuid5 under this namespace: given any row, membership is
# checkable (uuid5(namespace, key) == id), and no collected quote can collide with it.
SYNTHETIC_UUID_NAMESPACE = uuid.UUID("6a7f9f3e-8f7a-4b0e-b6d1-5f2c9d4e8a01")

_EARTH_RADIUS_KM = 6371.0088
_CRUISE_KMH = 720.0  # block-speed proxy, used only for plausible arrival times
_TURNAROUND_H = 0.6

QUOTE_COLUMNS = (
    "id",
    "source_code",
    "route_code",
    "origin_iata",
    "carrier_iata",
    "flight_number",
    "query_date",
    "travel_date",
    "advance_days",
    "dep_datetime_local",
    "arr_datetime_local",
    "fare_bucket",
    "base_fare",
    "taxes",
    "udf",
    "convenience_fee",
    "total_fare",
    "seats_shown",
    "refundable",
)

_TRUTH_COLUMNS = (
    "anomaly_id",
    "kind",
    "quote_id",
    "source_code",
    "route_code",
    "carrier_iata",
    "flight_number",
    "query_date",
    "travel_date",
    "advance_days",
    "field",
    "original_value",
    "injected_value",
)


@dataclass(frozen=True)
class SyntheticDataset:
    """Output of one generation run.

    ``quotes`` has one row per observed (channel, flight, query day, travel day) cell.
    ``anomalies`` is the ground truth: one row per quote deliberately damaged, with the
    value it replaced. ``sold_out`` records the cells where every fare bucket had
    closed — the observations that are missing on purpose, kept as data.
    """

    quotes: pd.DataFrame
    anomalies: pd.DataFrame
    sold_out: pd.DataFrame
    seed: int
    start_query_date: date
    days: int


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two coordinates, in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def lead_time_multipliers(
    cfg: SyntheticConfig, advance_days: NDArray[np.int64]
) -> NDArray[np.float64]:
    """Advance-purchase multiplier for each entry of ``advance_days``.

    Log-linear interpolation between the configured knots, clamped to the end knots
    outside their range. Log-linear keeps the structure multiplicative: between two
    knots, each day closer to departure scales the fare by a constant factor.
    """
    knot_days = np.array([k.days_before_departure for k in cfg.lead_time_knots], dtype=np.float64)
    knot_mult = np.array([k.multiplier for k in cfg.lead_time_knots], dtype=np.float64)
    order = np.argsort(knot_days)  # np.interp needs ascending x; knots are descending
    log_mult = np.interp(
        advance_days.astype(np.float64), knot_days[order], np.log(knot_mult)[order]
    )
    result: NDArray[np.float64] = np.exp(log_mult)
    return result


def _festival_surge(cfg: SyntheticConfig, dates: pd.DatetimeIndex) -> NDArray[np.float64]:
    """Festival demand multiplier per date: max over overlapping windows, floor 1.0."""
    surge = np.ones(len(dates), dtype=np.float64)
    for festival in cfg.festivals:
        lo = pd.Timestamp(festival.date - timedelta(days=festival.days_before))
        hi = pd.Timestamp(festival.date + timedelta(days=festival.days_after))
        mask = (dates >= lo) & (dates <= hi)
        surge[mask] = np.maximum(surge[mask], festival.surge)
    return surge


def _route_carrier_flights(
    cfg: SyntheticConfig,
    basket: BasketConfig,
    airport_coords: Mapping[str, tuple[float, float]],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """One row per synthetic flight: route, carrier, flight number, price level."""
    needed = {r.origin for r in basket.routes} | {r.dest for r in basket.routes}
    missing = sorted(code for code in needed if code not in airport_coords)
    if missing:
        raise ValueError(f"no coordinates for basket airports: {missing}")

    carrier_codes = list(cfg.carriers)
    weights = np.array([cfg.carriers[c].presence_weight for c in carrier_codes])
    weights = weights / weights.sum()

    rows: list[dict[str, object]] = []
    for route in basket.routes:
        o_lat, o_lon = airport_coords[route.origin]
        d_lat, d_lon = airport_coords[route.dest]
        dist = haversine_km(o_lat, o_lon, d_lat, d_lon)
        n_carriers = int(
            rng.integers(
                cfg.collection.carriers_per_route_min,
                cfg.collection.carriers_per_route_max + 1,
            )
        )
        chosen = rng.choice(carrier_codes, size=n_carriers, replace=False, p=weights)
        for carrier_ in chosen:
            carrier = str(carrier_)
            level = (
                (cfg.pricing.base_floor_inr + cfg.pricing.price_per_km_inr * dist)
                * cfg.carriers[carrier].fare_factor
                * float(rng.lognormal(0.0, cfg.pricing.route_effect_sigma))
            )
            for _ in range(cfg.collection.flights_per_route_carrier):
                rows.append(
                    {
                        "route_code": route.code,
                        "origin_iata": route.origin,
                        "carrier_iata": carrier,
                        "flight_number": f"{carrier}{int(rng.integers(100, 1000))}",
                        "distance_km": dist,
                        "level_fare": level,
                        "dep_hour": int(rng.integers(6, 22)),
                    }
                )
    flights = pd.DataFrame(rows)
    flights["duration_h"] = _TURNAROUND_H + flights["distance_km"] / _CRUISE_KMH
    flights.index.name = "flight_idx"
    return flights


def _bucket_close_days(
    cfg: SyntheticConfig,
    n_flights: int,
    demand: NDArray[np.float64],
    rng: np.random.Generator,
) -> NDArray[np.float64]:
    """Days-before-departure at which each bucket closes, per (flight, travel date).

    Shape ``(n_flights * n_dates, n_buckets)``. Higher demand pulls every closure
    earlier in time (a larger days-out value); noise makes each departure its own
    story. A value below zero means the bucket never closes.
    """
    mu = np.array(cfg.buckets.close_days_mu, dtype=np.float64)
    shift = 1.0 + cfg.buckets.demand_sensitivity * (demand - 1.0)
    per_fd_shift = np.tile(shift, n_flights)[:, None]
    noise = rng.normal(0.0, cfg.buckets.close_days_sigma, size=(n_flights * len(demand), len(mu)))
    result: NDArray[np.float64] = mu[None, :] * per_fd_shift + noise
    return result


def generate(
    cfg: SyntheticConfig,
    basket: BasketConfig,
    airport_coords: Mapping[str, tuple[float, float]],
    start_query_date: date,
    days: int,
) -> SyntheticDataset:
    """Generate ``days`` collection days of synthetic quotes for the whole basket."""
    if days < 1:
        raise ValueError("days must be >= 1")
    rng = np.random.default_rng(cfg.seed)

    flights = _route_carrier_flights(cfg, basket, airport_coords, rng)
    n_flights = len(flights)
    adv_grid = np.array(cfg.collection.advance_days_grid, dtype=np.int64)
    max_adv = int(adv_grid.max())

    # Every date that can appear as a travel date, indexed 0..n_dates-1 from the first
    # query date. Seasonality and bucket behaviour are keyed on this axis.
    n_dates = days + max_adv
    all_dates = pd.date_range(pd.Timestamp(start_query_date), periods=n_dates, freq="D")
    date_objects: NDArray[np.object_] = np.array(all_dates.date)
    dow_mult = np.array(cfg.dow_multiplier_vector(), dtype=np.float64)[all_dates.weekday]
    fest_mult = _festival_surge(cfg, all_dates)
    demand = dow_mult * fest_mult

    close_days = _bucket_close_days(cfg, n_flights, demand, rng)

    # The observation grid: flights x query days x advance points.
    n_cells = n_flights * days * len(adv_grid)
    flight_idx = np.repeat(np.arange(n_flights), days * len(adv_grid))
    query_off = np.tile(np.repeat(np.arange(days), len(adv_grid)), n_flights)
    adv = np.tile(adv_grid, n_flights * days)
    travel_off = query_off + adv

    # Lowest open bucket per cell; a cell with no open bucket is a sell-out.
    fd_key = flight_idx * n_dates + travel_off
    open_matrix = adv[:, None] > close_days[fd_key]
    any_open = open_matrix.any(axis=1)
    lowest_open = np.argmax(open_matrix, axis=1)

    # Price per cell: level x lead-time x seasonality x noise x bucket ladder.
    lt_by_adv = lead_time_multipliers(cfg, adv_grid)
    lt = lt_by_adv[np.searchsorted(adv_grid, adv)]
    season = demand[travel_off]
    daily_noise = rng.lognormal(0.0, cfg.pricing.daily_noise_sigma, size=n_cells)
    ladder = (1.0 + cfg.buckets.price_step) ** lowest_open
    level = flights["level_fare"].to_numpy()[flight_idx]
    base_fare = np.round(level * lt * season * daily_noise * ladder, 2)
    seats_shown = rng.integers(1, 10, size=n_cells)

    cells = pd.DataFrame(
        {
            "flight_idx": flight_idx,
            "query_off": query_off,
            "travel_off": travel_off,
            "advance_days": adv,
            "fare_bucket": lowest_open,
            "base_fare": base_fare,
            "seats_shown": seats_shown,
        }
    )

    sold_out = (
        cells.loc[~any_open, ["flight_idx", "query_off", "travel_off", "advance_days"]]
        .reset_index(drop=True)
        .join(flights[["route_code", "carrier_iata", "flight_number"]], on="flight_idx")
    )
    sold_out["query_date"] = date_objects[sold_out["query_off"].to_numpy()]
    sold_out["travel_date"] = date_objects[sold_out["travel_off"].to_numpy()]
    sold_out = sold_out.drop(columns=["flight_idx", "query_off", "travel_off"])

    cells = cells.loc[any_open].reset_index(drop=True)

    # One copy of the fare surface per sales channel; only the booking fee differs.
    per_source = []
    for source in cfg.sources:
        block = cells.copy()
        block["source_code"] = source.code
        block["convenience_fee"] = round(source.convenience_fee_inr, 2)
        per_source.append(block)
    quotes = pd.concat(per_source, ignore_index=True)

    quotes = quotes.join(
        flights[
            ["route_code", "origin_iata", "carrier_iata", "flight_number", "dep_hour", "duration_h"]
        ],
        on="flight_idx",
    )
    quotes["query_date"] = date_objects[quotes["query_off"].to_numpy()]
    quotes["travel_date"] = date_objects[quotes["travel_off"].to_numpy()]
    dep_naive = all_dates.to_numpy()[quotes["travel_off"].to_numpy()] + quotes[
        "dep_hour"
    ].to_numpy().astype("timedelta64[h]")
    quotes["dep_datetime_local"] = dep_naive
    quotes["arr_datetime_local"] = dep_naive + (
        (quotes["duration_h"].to_numpy() * 60).round().astype("timedelta64[m]")
    )
    quotes["udf"] = quotes["origin_iata"].map(lambda o: float(cfg.udf_for(str(o))))
    quotes["taxes"] = np.round(quotes["base_fare"].to_numpy() * cfg.pricing.tax_rate, 2)
    quotes["total_fare"] = np.round(
        quotes[["base_fare", "taxes", "udf", "convenience_fee"]].sum(axis=1).to_numpy(), 2
    )
    quotes["refundable"] = quotes["carrier_iata"].eq("AI")

    # Deterministic identity per observation slot (price excluded: the id names the
    # cell, the content hash — computed by the seeder — names what was seen in it).
    slot_keys = (
        quotes["source_code"]
        + "|"
        + quotes["route_code"]
        + "|"
        + quotes["flight_number"]
        + "|"
        + quotes["query_date"].astype(str)
        + "|"
        + quotes["travel_date"].astype(str)
    )
    quotes["id"] = [uuid.uuid5(SYNTHETIC_UUID_NAMESPACE, key) for key in slot_keys]

    anomalies = _inject_anomalies(cfg, quotes, days, rng)

    return SyntheticDataset(
        quotes=quotes[list(QUOTE_COLUMNS)].copy(),
        anomalies=anomalies,
        sold_out=sold_out,
        seed=cfg.seed,
        start_query_date=start_query_date,
        days=days,
    )


def _inject_anomalies(
    cfg: SyntheticConfig,
    quotes: pd.DataFrame,
    days: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Damage a known set of quotes in place; return the ground-truth table."""
    truth_rows: list[dict[str, object]] = []
    used: set[int] = set()

    def record(
        anomaly_id: str, kind: AnomalyKind, idx: int, original: float, injected: float
    ) -> None:
        row = quotes.loc[idx]
        truth_rows.append(
            {
                "anomaly_id": anomaly_id,
                "kind": kind.value,
                "quote_id": str(row["id"]),
                "source_code": row["source_code"],
                "route_code": row["route_code"],
                "carrier_iata": row["carrier_iata"],
                "flight_number": row["flight_number"],
                "query_date": str(row["query_date"]),
                "travel_date": str(row["travel_date"]),
                "advance_days": int(row["advance_days"]),
                "field": "total_fare",
                "original_value": round(float(original), 2),
                "injected_value": round(float(injected), 2),
            }
        )

    def rescale(idx: int, factor: float) -> tuple[float, float]:
        """Scale one quote's base fare, keeping components consistent."""
        original_total = float(quotes.at[idx, "total_fare"])
        new_base = round(float(quotes.at[idx, "base_fare"]) * factor, 2)
        new_taxes = round(new_base * cfg.pricing.tax_rate, 2)
        new_total = round(
            new_base
            + new_taxes
            + float(quotes.at[idx, "udf"])
            + float(quotes.at[idx, "convenience_fee"]),
            2,
        )
        quotes.at[idx, "base_fare"] = new_base
        quotes.at[idx, "taxes"] = new_taxes
        quotes.at[idx, "total_fare"] = new_total
        return original_total, new_total

    for spec in cfg.anomalies:
        if spec.count == 0:
            continue
        if spec.kind is AnomalyKind.STALE_REPEAT:
            _inject_stale_runs(quotes, days, rng, spec.count, spec.run_length_days, record)
            continue

        candidates = np.setdiff1d(
            np.arange(len(quotes)), np.fromiter(used, dtype=np.int64, count=len(used))
        )
        picks = rng.choice(candidates, size=min(spec.count, len(candidates)), replace=False)
        used.update(int(p) for p in picks)
        for seq, pos in enumerate(picks, start=1):
            idx = int(quotes.index[int(pos)])
            anomaly_id = f"{spec.kind.value}-{seq:03d}"
            if spec.kind is AnomalyKind.PRICE_SPIKE:
                original, injected = rescale(idx, spec.magnitude)
            elif spec.kind is AnomalyKind.FAT_FINGER:
                original, injected = rescale(idx, 1.0 / spec.magnitude)
            else:  # COMPONENT_MISMATCH: total drifts away from its parts
                original = float(quotes.at[idx, "total_fare"])
                injected = round(original + spec.magnitude, 2)
                quotes.at[idx, "total_fare"] = injected
            record(anomaly_id, spec.kind, idx, original, injected)

    return pd.DataFrame(truth_rows, columns=list(_TRUTH_COLUMNS))


def _inject_stale_runs(
    quotes: pd.DataFrame,
    days: int,
    rng: np.random.Generator,
    count: int,
    run_length: int,
    record: Callable[[str, AnomalyKind, int, float, float], None],
) -> None:
    """Freeze a collector cell's price across consecutive collection days.

    A stale cache shows the same fare for a (channel, route, flight, advance-window)
    cell day after day while neighbouring cells move — the zero-variance run the
    watchdog must flag. The first day of the run is genuine and stays unrecorded; the
    following ``run_length - 1`` days are overwritten with its prices and recorded.
    """
    if days < run_length:
        return
    grouped = quotes.groupby(
        ["source_code", "route_code", "carrier_iata", "flight_number", "advance_days"],
        sort=True,
    )
    # Only cells observed on every collection day can host a clean run: a sell-out
    # hole inside the run would break the "identical price, consecutive days" signal.
    complete = [name for name, group in grouped if len(group) == days]
    if not complete:
        return
    chosen_pos = rng.choice(len(complete), size=min(count, len(complete)), replace=False)
    for seq, group_pos in enumerate(chosen_pos, start=1):
        group = grouped.get_group(complete[int(group_pos)]).sort_values("query_date")
        start = int(rng.integers(0, days - run_length + 1))
        run = group.iloc[start : start + run_length]
        anchor = run.iloc[0]
        anomaly_id = f"{AnomalyKind.STALE_REPEAT.value}-{seq:03d}"
        for idx_ in run.index[1:]:
            idx = int(idx_)
            original = float(quotes.at[idx, "total_fare"])
            quotes.at[idx, "base_fare"] = float(anchor["base_fare"])
            quotes.at[idx, "taxes"] = float(anchor["taxes"])
            quotes.at[idx, "total_fare"] = float(anchor["total_fare"])
            record(anomaly_id, AnomalyKind.STALE_REPEAT, idx, original, float(anchor["total_fare"]))
