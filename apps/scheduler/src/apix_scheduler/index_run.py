"""``python -m apix_scheduler.index_run`` — ``make index-run DATE=...`` calls this.

Two things live in this module:

* :func:`run` — a synthetic, in-process demonstration of the index maths (no database,
  no network): GEKS-Törnqvist per (route, advance-purchase window) cell, a route index
  booking-profile-weighted across windows, sub-indices by carrier type and by advance
  window, and a national index attempt. Kept for its own test suite
  (``tests/scheduler/test_index_run.py``) as a fast, DB-free check that the aggregation
  hierarchy wires together correctly against the real shipped config.
* :func:`compute_and_persist` — the real, database-backed path ``main()`` (and so
  ``make index-run``) actually calls: reads real ``fare_quote`` rows for the window,
  cleans them (:mod:`apix_core.clean`), computes the same aggregation hierarchy, and
  writes ``data_snapshot``, ``method_config``, ``index_run``, ``series``,
  ``index_value``, ``revision_log`` and the ``index_value_quote`` lineage in one
  transaction (see :mod:`apix_core.index.run`). This is still not a Prefect flow —
  scheduling/orchestration remains a later concern — but the numbers it publishes are
  real, not a demonstration.

Both paths report a cell or level that cannot be computed as a skip with a reason,
never silently dropped or guessed at (CLAUDE.md principles 1 and 2). The national index
in particular is expected to come back unpublishable against the shipped
``config/basket.yaml``, where every route's ``dgca_pax_share`` is null until Phase 2
loads the real DGCA release — that refusal is the correct, intended behaviour.
"""

from __future__ import annotations

import argparse
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

import pandas as pd
import structlog
from sqlalchemy import create_engine, func, insert, select
from sqlalchemy.orm import Session

from apix_core.clean import CELL_IDENTITY, clean_quotes
from apix_core.config import (
    config_hash,
    find_config_dir,
    load_basket,
    load_cleaning,
    load_method,
    load_synthetic,
)
from apix_core.index import (
    geks_tornqvist,
    national_index,
    route_index,
    run_index,
    sub_index_by,
    weighted_geometric_rollup,
)
from apix_core.models import (
    CollectionRun,
    DataSnapshot,
    FareQuote,
    FareQuoteClean,
    Frequency,
    IndexRun,
    IndexValue,
    IndexValueQuote,
    MethodConfig,
    RevisionLog,
    Route,
    RunStatus,
    Series,
    Source,
)
from apix_core.provenance.hashing import sha256_hex
from apix_core.seeding.reference import load_airport_coords, read_seed_csv
from apix_core.settings import get_settings
from apix_core.testing.synthetic import generate

if TYPE_CHECKING:
    from pathlib import Path

    from apix_core.config.basket import BasketConfig
    from apix_core.config.method import MethodConfigFile

log = structlog.get_logger(__name__)

ELEMENTARY_COLUMNS = (
    "route_code",
    "advance_window",
    "carrier_type",
    "index_value",
    "n_quotes",
    "coverage_pct",
)


@dataclass(frozen=True)
class CellSkip:
    """A (route, advance_window, carrier) cell that could not be indexed, and why."""

    route_code: str
    advance_window: str
    carrier_iata: str
    reason: str


def _advance_window_for(basket: BasketConfig, advance_days: int) -> str | None:
    for window in basket.advance_windows:
        if window.min_days <= advance_days <= window.max_days:
            return window.code
    return None


def _carrier_type_by_iata(seeds_dir: Path) -> dict[str, str]:
    return {row["iata"]: row["carrier_type"] for row in read_seed_csv(seeds_dir / "carriers.csv")}


def _cell_panel(cell_quotes: pd.DataFrame) -> pd.DataFrame:
    """One row per (period, product) for a single (route, advance_window, carrier)
    cell: period is the collection day, product is the specific flight/channel/
    advance-days point.

    An advance-purchase window (e.g. ``AP00_03``) can span more than one point on
    ``config/synthetic.yaml``'s collection grid (1 and 2 days out both fall in it), so
    the same flight/channel appears twice within one collection day at two different
    prices. ``advance_days`` has to be part of the product identity or those two
    genuinely different price points collide into one duplicate-indexed "product" and
    break the panel — a 1-day-out fare and a 2-day-out fare are different products on
    the fare curve, not two observations of the same one.
    """
    product_id = (
        cell_quotes["carrier_iata"]
        + "|"
        + cell_quotes["flight_number"]
        + "|"
        + cell_quotes["source_code"]
        + "|"
        + cell_quotes["advance_days"].astype(str)
    )
    return pd.DataFrame(
        {
            "period": cell_quotes["query_date"],
            "product_id": product_id,
            "price": cell_quotes["total_fare"].astype(float),
            # No expenditure/quantity data exists at this level — every observed
            # product counts equally, consistent with Jevons's no-weight philosophy
            # (apix_core.index.elementary).
            "share": 1.0,
        }
    )


def build_elementary_index(
    quotes: pd.DataFrame,
    basket: BasketConfig,
    carrier_type_by_iata: dict[str, str],
    as_of: date,
    window_days: int,
) -> tuple[pd.DataFrame, list[CellSkip]]:
    """GEKS-Törnqvist per (route_code, advance_window, carrier_iata) cell, evaluated
    at ``as_of`` against the rest of the window.

    Cells with too little data to estimate (fewer than two periods, or a pair of
    periods sharing no product) are skipped and recorded, never fabricated.
    """
    work = quotes.copy()
    work["advance_window"] = work["advance_days"].map(lambda d: _advance_window_for(basket, d))
    work["carrier_type"] = work["carrier_iata"].map(carrier_type_by_iata)

    rows: list[dict[str, object]] = []
    skips: list[CellSkip] = []
    groups = work.dropna(subset=["advance_window"]).groupby(
        ["route_code", "advance_window", "carrier_iata"], sort=True
    )
    for (route_code, advance_window, carrier_iata), cell_quotes in groups:
        panel = _cell_panel(cell_quotes)
        try:
            window_index = geks_tornqvist(panel, window_days=window_days)
        except ValueError as exc:
            skips.append(
                CellSkip(str(route_code), str(advance_window), str(carrier_iata), str(exc))
            )
            continue

        first_products = set(panel.loc[panel["period"] == panel["period"].min(), "product_id"])
        last_period = as_of
        if last_period not in window_index.index:
            skips.append(
                CellSkip(
                    str(route_code),
                    str(advance_window),
                    str(carrier_iata),
                    f"no observation on {as_of.isoformat()} (the as-of date)",
                )
            )
            continue
        last_products = set(panel.loc[panel["period"] == last_period, "product_id"])
        coverage_pct = 100.0 * len(first_products & last_products) / len(first_products)

        rows.append(
            {
                "route_code": route_code,
                "advance_window": advance_window,
                "carrier_type": carrier_type_by_iata.get(str(carrier_iata), "UNKNOWN"),
                "index_value": float(window_index.loc[last_period]),
                "n_quotes": len(cell_quotes.loc[cell_quotes["query_date"] == last_period]),
                "coverage_pct": coverage_pct,
            }
        )
    elementary = pd.DataFrame(rows, columns=list(ELEMENTARY_COLUMNS))
    return elementary, skips


@dataclass(frozen=True)
class IndexRunReport:
    """Everything one CLI run computed, typed so callers don't index into a dict."""

    as_of: date
    index_reference_value: float
    elementary: pd.DataFrame
    routes: pd.DataFrame
    national: pd.DataFrame | None
    national_error: str | None
    excluded_routes: list[str]
    by_carrier_type: pd.DataFrame
    by_advance_window: pd.DataFrame
    skipped_cells: list[CellSkip]


def run(as_of: date, days: int) -> IndexRunReport:
    """Generate the synthetic dataset and compute the full aggregation hierarchy."""
    config_dir = find_config_dir()
    repo_root = config_dir.parent
    seeds_dir = repo_root / "db" / "seeds"

    basket = load_basket(config_dir)
    method = load_method(config_dir)
    synthetic_cfg = load_synthetic(config_dir)

    start_query_date = as_of - timedelta(days=days - 1)
    dataset = generate(
        synthetic_cfg, basket, load_airport_coords(seeds_dir), start_query_date, days
    )
    carrier_type_by_iata = _carrier_type_by_iata(seeds_dir)

    elementary, skips = build_elementary_index(
        dataset.quotes, basket, carrier_type_by_iata, as_of, window_days=days
    )
    if elementary.empty:
        raise RuntimeError(
            "no (route, advance_window, carrier) cell could be indexed for "
            f"{as_of.isoformat()} — try a longer --days window"
        )

    # Collapse the carrier dimension (n_quotes-weighted) before rolling up to route
    # level: route_index expects one row per (route_code, advance_window).
    by_route_window = weighted_geometric_rollup(
        elementary, ["route_code", "advance_window"], "n_quotes"
    )
    routes = route_index(by_route_window, method.booking_profile.weights)

    dgca_pax_share = {r.code: float(r.dgca_pax_share) for r in basket.routes if r.dgca_pax_share}
    national: pd.DataFrame | None
    excluded_routes: list[str]
    national_error: str | None
    try:
        national, excluded_routes = national_index(routes, dgca_pax_share)
        national_error = None
    except ValueError as exc:
        national, excluded_routes = None, []
        national_error = str(exc)

    by_carrier_type = sub_index_by(elementary, "carrier_type", "n_quotes")
    by_advance_window = sub_index_by(elementary, "advance_window", "n_quotes")

    return IndexRunReport(
        as_of=as_of,
        index_reference_value=method.index_reference_value,
        elementary=elementary,
        routes=routes,
        national=national,
        national_error=national_error,
        excluded_routes=excluded_routes,
        by_carrier_type=by_carrier_type,
        by_advance_window=by_advance_window,
        skipped_cells=skips,
    )


def _log_report(result: IndexRunReport) -> None:
    """Emit the run as structured log events — CLAUDE.md: structlog only, no print().

    Every level gets its own event so a run can be audited from the log stream alone,
    the same way a real ``apix_scheduler`` flow would be: nothing here is only
    readable from a terminal.
    """
    as_of = str(result.as_of)
    log.info(
        "index_run_route_index",
        as_of=as_of,
        index_reference_value=result.index_reference_value,
        routes=result.routes.to_dict(orient="records"),
    )
    log.info(
        "index_run_sub_index_by_carrier_type",
        as_of=as_of,
        breakdown=result.by_carrier_type.to_dict(orient="records"),
    )
    log.info(
        "index_run_sub_index_by_advance_window",
        as_of=as_of,
        breakdown=result.by_advance_window.to_dict(orient="records"),
    )
    national = result.national
    log.info(
        "index_run_national_index",
        as_of=as_of,
        published=national is not None,
        value=(None if national is None else national.to_dict(orient="records")),
        excluded_routes=result.excluded_routes,
        reason=result.national_error,
    )
    skips = result.skipped_cells
    log.info(
        "index_run_skipped_cells",
        as_of=as_of,
        count=len(skips),
        examples=[
            {
                "route_code": s.route_code,
                "advance_window": s.advance_window,
                "carrier_iata": s.carrier_iata,
                "reason": s.reason,
            }
            for s in skips[:10]
        ],
    )


_SERIES_HEADLINE = "APIX.ALL.M"


# The window's own level at both ends is what a splice needs: the value it enters this
# window with and the value it leaves it with. run_index() only cares about the ratio
# between the two, so it does not matter that "prior" and "current" here come from one
# continuous GEKS chain rather than two independently re-estimated windows — see
# apix_core.index.splice's module docstring ("any consistent normalisation cancels").
@dataclass(frozen=True)
class _CellWindow:
    route_code: str
    advance_window: str
    carrier_type: str
    prior_value: float
    current_value: float
    n_quotes: int
    coverage_pct: float


def _load_window_quotes(session: Session, start_query_date: date, as_of: date) -> pd.DataFrame:
    """Real ``fare_quote`` rows for ``[start_query_date, as_of]``, joined to the route
    and source codes the elementary-index panel and ``clean_quotes()`` both need.
    """
    columns = (
        "id",
        "collected_at",
        "source_id",
        "source_code",
        "route_id",
        "route_code",
        "origin_iata",
        "carrier_iata",
        "flight_number",
        "dep_datetime_local",
        "travel_date",
        "query_date",
        "advance_days",
        "stops",
        "refundable",
        "baggage_included",
        "base_fare",
        "taxes",
        "udf",
        "convenience_fee",
        "total_fare",
    )
    stmt = (
        select(
            FareQuote.id,
            FareQuote.collected_at,
            FareQuote.source_id,
            Source.code.label("source_code"),
            FareQuote.route_id,
            Route.code.label("route_code"),
            Route.origin_iata,
            FareQuote.carrier_iata,
            FareQuote.flight_number,
            FareQuote.dep_datetime_local,
            FareQuote.travel_date,
            FareQuote.query_date,
            FareQuote.advance_days,
            FareQuote.stops,
            FareQuote.refundable,
            FareQuote.baggage_included,
            FareQuote.base_fare,
            FareQuote.taxes,
            FareQuote.udf,
            FareQuote.convenience_fee,
            FareQuote.total_fare,
        )
        .join(Source, Source.id == FareQuote.source_id)
        .join(Route, Route.id == FareQuote.route_id)
        .where(FareQuote.query_date.between(start_query_date, as_of))
    )
    rows = [dict(row) for row in session.execute(stmt).mappings().all()]
    return pd.DataFrame(rows, columns=list(columns))


def _load_collection_runs(session: Session, start_query_date: date, as_of: date) -> pd.DataFrame:
    start_dt = datetime.combine(start_query_date, time.min, tzinfo=UTC)
    end_dt = datetime.combine(as_of, time.max, tzinfo=UTC)
    rows = session.execute(
        select(
            CollectionRun.source_id,
            CollectionRun.route_id,
            CollectionRun.started_at,
            CollectionRun.status,
        ).where(CollectionRun.started_at.between(start_dt, end_dt))
    ).all()
    frame = pd.DataFrame(rows, columns=["source_id", "route_id", "started_at", "status"])
    if frame.empty:
        return pd.DataFrame(columns=["source_id", "route_id", "query_date", "status"])
    frame["query_date"] = frame["started_at"].map(lambda dt: dt.date())
    frame["status"] = frame["status"].map(lambda s: s.value if hasattr(s, "value") else s)
    return frame[["source_id", "route_id", "query_date", "status"]]


def _build_expected_cells(quotes: pd.DataFrame, collection_runs: pd.DataFrame) -> pd.DataFrame:
    """The sampling grid the collector is inferred to have intended: every
    (source, route, carrier, flight) combination seen anywhere in the window, expected
    again on every day that source's collection run succeeded.

    Real collection-run tracking for this dataset is per (source, day), not per route
    (``apix_core.testing.seed`` writes ``collection_run.route_id = NULL`` — collection
    happens per channel, not per route) — so a gap here can only ever be classified
    "not_collected", never "sold_out": there is no per-route run record saying the
    collector looked at this specific route and found nothing. That is an honest
    reflection of what is actually known, not a defect in this function.
    """
    if quotes.empty or collection_runs.empty:
        return pd.DataFrame(columns=list(CELL_IDENTITY))
    flights = quotes[
        ["source_id", "route_id", "carrier_iata", "flight_number", "advance_days"]
    ].drop_duplicates()
    ran = collection_runs.loc[
        collection_runs["status"].isin(("SUCCEEDED", "PARTIAL")), ["source_id", "query_date"]
    ].drop_duplicates()
    if ran.empty:
        return pd.DataFrame(columns=list(CELL_IDENTITY))
    grid = flights.merge(ran, on="source_id", how="inner")
    grid["travel_date"] = [
        query_date + timedelta(days=int(advance_days))
        for query_date, advance_days in zip(grid["query_date"], grid["advance_days"], strict=True)
    ]
    return grid[list(CELL_IDENTITY)]


def _build_cell_windows(
    quotes: pd.DataFrame,
    basket: BasketConfig,
    carrier_type_by_iata: dict[str, str],
    as_of: date,
    window_days: int,
    outlier_quote_ids: set[uuid.UUID],
) -> tuple[list[_CellWindow], list[CellSkip]]:
    """Per (route, advance_window, carrier) cell: the GEKS-Törnqvist window's own level
    at the start and at the end of the window. Outlier-flagged quotes are excluded
    first — the index is computed on screened data, never on the raw feed.
    """
    work = quotes.loc[~quotes["id"].isin(outlier_quote_ids)].copy()
    work["advance_window"] = work["advance_days"].map(lambda d: _advance_window_for(basket, d))
    work["carrier_type"] = work["carrier_iata"].map(carrier_type_by_iata)

    windows: list[_CellWindow] = []
    skips: list[CellSkip] = []
    groups = work.dropna(subset=["advance_window"]).groupby(
        ["route_code", "advance_window", "carrier_iata"], sort=True
    )
    for (route_code, advance_window, carrier_iata), cell_quotes in groups:
        panel = _cell_panel(cell_quotes)
        try:
            window_index = geks_tornqvist(panel, window_days=window_days)
        except ValueError as exc:
            skips.append(
                CellSkip(str(route_code), str(advance_window), str(carrier_iata), str(exc))
            )
            continue
        if as_of not in window_index.index:
            skips.append(
                CellSkip(
                    str(route_code),
                    str(advance_window),
                    str(carrier_iata),
                    f"no observation on {as_of.isoformat()} (the as-of date)",
                )
            )
            continue
        first_products = set(panel.loc[panel["period"] == panel["period"].min(), "product_id"])
        last_products = set(panel.loc[panel["period"] == as_of, "product_id"])
        coverage_pct = 100.0 * len(first_products & last_products) / len(first_products)
        windows.append(
            _CellWindow(
                route_code=str(route_code),
                advance_window=str(advance_window),
                carrier_type=carrier_type_by_iata.get(str(carrier_iata), "UNKNOWN"),
                prior_value=float(window_index.iloc[0]),
                current_value=float(window_index.loc[as_of]),
                n_quotes=int((cell_quotes["query_date"] == as_of).sum()),
                coverage_pct=coverage_pct,
            )
        )
    return windows, skips


def _cell_windows_to_frame(windows: list[_CellWindow]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "route_code": [w.route_code for w in windows],
            "advance_window": [w.advance_window for w in windows],
            "carrier_type": [w.carrier_type for w in windows],
            "index_value_prior": [w.prior_value for w in windows],
            "index_value_current": [w.current_value for w in windows],
            "n_quotes": [w.n_quotes for w in windows],
            "coverage_pct": [w.coverage_pct for w in windows],
        }
    )


def _rollup_hierarchy(
    elementary: pd.DataFrame, value_col: str, basket: BasketConfig, method: MethodConfigFile
) -> dict[str, tuple[float, int, float]]:
    """One cross-section — headline, route, carrier-type and advance-window series —
    at whichever end of the window ``value_col`` names.
    """
    work = elementary.rename(columns={value_col: "index_value"})[
        ["route_code", "advance_window", "carrier_type", "index_value", "n_quotes", "coverage_pct"]
    ]
    by_route_window = weighted_geometric_rollup(work, ["route_code", "advance_window"], "n_quotes")
    routes = route_index(by_route_window, method.booking_profile.weights)

    result: dict[str, tuple[float, int, float]] = {}
    for _, row in routes.iterrows():
        result[f"APIX.ROUTE.{row['route_code']}.M"] = (
            float(row["index_value"]),
            int(row["n_quotes"]),
            float(row["coverage_pct"]),
        )

    dgca_pax_share = {r.code: float(r.dgca_pax_share) for r in basket.routes if r.dgca_pax_share}
    try:
        national, _excluded = national_index(routes, dgca_pax_share)
        row = national.iloc[0]
        result[_SERIES_HEADLINE] = (
            float(row["index_value"]),
            int(row["n_quotes"]),
            float(row["coverage_pct"]),
        )
    except ValueError as exc:
        log.info("index_run_national_unpublishable", value_col=value_col, reason=str(exc))

    for _, row in sub_index_by(work, "carrier_type", "n_quotes").iterrows():
        result[f"APIX.CARRIERTYPE.{row['carrier_type']}.M"] = (
            float(row["index_value"]),
            int(row["n_quotes"]),
            float(row["coverage_pct"]),
        )
    for _, row in sub_index_by(work, "advance_window", "n_quotes").iterrows():
        result[f"APIX.WINDOW.{row['advance_window']}.M"] = (
            float(row["index_value"]),
            int(row["n_quotes"]),
            float(row["coverage_pct"]),
        )
    return result


def _series_dimensions(series_code: str) -> dict[str, str]:
    if series_code == _SERIES_HEADLINE:
        return {"scope": "national"}
    parts = series_code.split(".")
    if parts[1] == "ROUTE":
        return {"route_code": parts[2]}
    if parts[1] == "CARRIERTYPE":
        return {"carrier_type": parts[2]}
    if parts[1] == "WINDOW":
        return {"advance_window": parts[2]}
    raise ValueError(f"unrecognised series code shape: {series_code}")


def _reference_period(method: MethodConfigFile) -> date:
    year_str, month_str = method.price_reference_period.split("-")
    return date(int(year_str), int(month_str), 1)


def _ensure_series(session: Session, series_codes: set[str]) -> dict[str, uuid.UUID]:
    existing: dict[str, uuid.UUID] = dict(
        session.execute(select(Series.code, Series.id).where(Series.code.in_(series_codes)))
        .tuples()
        .all()
    )
    missing = series_codes - set(existing)
    for code in sorted(missing):
        row = Series(
            id=uuid.uuid4(),
            code=code,
            description=f"APIx series {code}",
            dimensions=_series_dimensions(code),
            frequency=Frequency.MONTHLY,
        )
        session.add(row)
        existing[code] = row.id
    if missing:
        session.flush()
    return existing


def _load_published(session: Session, series_ids: dict[str, uuid.UUID]) -> pd.DataFrame:
    """The current best estimate for every already-published (series, period): the
    value from that period's most recent vintage, never a mix of vintages.

    A period can have more than one ``index_value`` row — one per run that has ever
    computed it (see ``IndexValue``'s docstring) — so this must rank by
    ``(vintage_date, computed_at)`` and keep only the newest, the same pattern
    ``apix_api.queries.latest_values_multi`` uses to serve the API. Without this, a
    second run for a period already published (a corrected snapshot, or simply
    ``index-run`` invoked twice) would hand ``run_index`` more than one row per
    (series, period) here, splicing onto an ambiguous history.
    """
    if not series_ids:
        return pd.DataFrame(columns=["series_code", "period", "value"])
    id_to_code = {v: k for k, v in series_ids.items()}
    rank = (
        func.row_number()
        .over(
            partition_by=(IndexValue.series_id, IndexValue.period),
            order_by=(IndexRun.vintage_date.desc(), IndexRun.computed_at.desc()),
        )
        .label("rank")
    )
    subq = (
        select(IndexValue.series_id, IndexValue.period, IndexValue.value, rank)
        .join(IndexRun, IndexRun.id == IndexValue.index_run_id)
        .where(IndexValue.series_id.in_(series_ids.values()))
        .subquery()
    )
    rows = session.execute(
        select(subq.c.series_id, subq.c.period, subq.c.value).where(subq.c.rank == 1)
    ).all()
    return pd.DataFrame(
        [
            {"series_code": id_to_code[series_id], "period": period, "value": float(value)}
            for series_id, period, value in rows
        ],
        columns=["series_code", "period", "value"],
    )


def _clean_rows_for_insert(clean: pd.DataFrame, ids: list[uuid.UUID]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = clean.reset_index(drop=True).to_dict(orient="records")
    for record, row_id in zip(records, ids, strict=True):
        record["id"] = row_id
        record["quality_vector"] = dict(record["quality_vector"])
        for nullable in ("quote_id", "quote_collected_at", "outlier_rule", "imputation_method"):
            if pd.isna(record.get(nullable)):
                record[nullable] = None
    return records


@dataclass(frozen=True)
class IndexRunPersistResult:
    """Everything one real, database-backed index run wrote."""

    index_run_id: uuid.UUID
    snapshot_id: uuid.UUID
    vintage_date: date
    period: date
    published_series: list[str]
    skipped_series: list[str]
    revision_count: int


def compute_and_persist(session: Session, as_of: date, days: int) -> IndexRunPersistResult:
    """The database-backed counterpart to :func:`run`.

    Reads real ``fare_quote`` rows for the window, runs them through
    :func:`apix_core.clean.clean_quotes`, computes the same aggregation hierarchy
    :func:`run` demonstrates against synthetic data, and persists ``data_snapshot``,
    ``method_config``, ``index_run``, ``series``, ``index_value``, ``revision_log`` and
    the ``index_value_quote`` lineage in one transaction. ``make index-run`` calls this.

    Every run publishes exactly one period — ``as_of``'s calendar month — spliced onto
    whatever was already published for the month before it (or, for a series with no
    history yet, seeded at ``config/method.yaml``'s ``index_reference_value``). Running
    this twice for the same ``--date`` with different underlying data (more quotes
    collected, a corrected snapshot) is how a period gets more than one vintage: each
    call is a new ``index_run`` with its own ``vintage_date``, and the period's earlier
    ``index_value`` rows are never overwritten.
    """
    config_dir = find_config_dir()
    repo_root = config_dir.parent
    seeds_dir = repo_root / "db" / "seeds"

    basket = load_basket(config_dir)
    method = load_method(config_dir)
    cleaning = load_cleaning(config_dir)
    carrier_type_by_iata = _carrier_type_by_iata(seeds_dir)

    start_query_date = as_of - timedelta(days=days - 1)
    quotes = _load_window_quotes(session, start_query_date, as_of)
    if quotes.empty:
        raise RuntimeError(
            f"no fare_quote rows with query_date in [{start_query_date}, {as_of}] — "
            "seed or collect data for this window before running the index"
        )
    collection_runs = _load_collection_runs(session, start_query_date, as_of)
    expected_cells = _build_expected_cells(quotes, collection_runs)

    snapshot_id = uuid.uuid4()
    clean_result = clean_quotes(
        quotes=quotes,
        expected_cells=expected_cells,
        collection_runs=collection_runs,
        carrier_type_by_iata=carrier_type_by_iata,
        # Every quote reaching fare_quote in this codebase already carries an itemised
        # base/taxes/udf split (the synthetic generator always itemises; a real
        # collector decomposes at ingest) — so no origin airport's UDF is ever actually
        # looked up here. Deriving from a non-itemising source is later-phase scope.
        airport_udf={},
        snapshot_id=str(snapshot_id),
        config=cleaning,
    )

    persistable_clean = clean_result.clean.dropna(subset=["dep_hour_bucket", "stops"]).reset_index(
        drop=True
    )
    dropped_unresolvable = len(clean_result.clean) - len(persistable_clean)
    if dropped_unresolvable:
        log.info(
            "index_run_imputed_rows_dropped_no_schedule",
            count=dropped_unresolvable,
            reason="imputed row has no known flight schedule to backfill dep_hour_bucket/stops "
            "from — never guessed, see apix_core.clean.pipeline",
        )

    clean_ids = [uuid.uuid4() for _ in range(len(persistable_clean))]
    persistable_clean["clean_id"] = clean_ids
    persistable_clean["query_date"] = [
        travel_date - timedelta(days=int(advance_days))
        for travel_date, advance_days in zip(
            persistable_clean["travel_date"], persistable_clean["advance_days"], strict=True
        )
    ]
    clean_rows = _clean_rows_for_insert(
        persistable_clean.drop(columns=["clean_id", "query_date"]), clean_ids
    )

    outlier_quote_ids = set(
        clean_result.clean.loc[clean_result.clean["is_outlier"], "quote_id"].dropna()
    )
    cell_windows, skips = _build_cell_windows(
        quotes, basket, carrier_type_by_iata, as_of, days, outlier_quote_ids
    )
    if not cell_windows:
        raise RuntimeError(
            f"no (route, advance_window, carrier) cell could be indexed for {as_of.isoformat()}"
        )
    if skips:
        log.info("index_run_skipped_cells", as_of=as_of.isoformat(), count=len(skips))
    elementary = _cell_windows_to_frame(cell_windows)

    current_period = as_of.replace(day=1)
    prior_period = (current_period - timedelta(days=1)).replace(day=1)
    current_hierarchy = _rollup_hierarchy(elementary, "index_value_current", basket, method)
    prior_hierarchy = _rollup_hierarchy(elementary, "index_value_prior", basket, method)

    method_hash = config_hash(method)
    content_hash = sha256_hex(
        "|".join(
            sorted(
                f"{row['quote_id']}:{row['total_fare']}" for row in clean_rows if row["quote_id"]
            )
        ).encode("utf-8")
    )

    method_config_row = session.execute(
        select(MethodConfig).where(MethodConfig.config_hash == method_hash)
    ).scalar_one_or_none()
    if method_config_row is None:
        method_config_row = MethodConfig(
            id=uuid.uuid4(), config_hash=method_hash, config=method.model_dump(mode="json")
        )
        session.add(method_config_row)
        session.flush()

    snapshot = DataSnapshot(
        id=snapshot_id,
        row_count=len(clean_rows),
        content_hash=content_hash,
        description=f"index_run as_of={as_of.isoformat()} days={days}",
    )
    session.add(snapshot)
    session.flush()

    if clean_rows:
        session.execute(insert(FareQuoteClean), clean_rows)

    computed_at = datetime.now(tz=UTC)
    index_run_row = IndexRun(
        id=uuid.uuid4(),
        snapshot_id=snapshot_id,
        method_config_id=method_config_row.id,
        vintage_date=as_of,
        computed_at=computed_at,
        status=RunStatus.SUCCEEDED,
        released_at=computed_at,
    )
    session.add(index_run_row)
    session.flush()

    series_ids = _ensure_series(session, set(current_hierarchy) | set(prior_hierarchy))
    published = _load_published(session, series_ids)

    window_indices: dict[str, pd.Series] = {}
    coverage: dict[str, tuple[int, float]] = {}
    bootstrap_series: set[str] = set()
    for series_code, (current_value, n_quotes, coverage_pct) in current_hierarchy.items():
        has_history = not published.loc[published["series_code"] == series_code].empty
        # The window's own prior-period value, on whatever internal scale
        # ``current_hierarchy``/``prior_hierarchy`` share — never the published
        # reference value, which lives on the *published* scale instead (splice()
        # only ever uses ratios *within* window_indices, so the two scales must not
        # be mixed). Falls back to current_value (a same-period ratio of 1) when this
        # run's window has no prior-period observation for the series at all.
        prior_entry = prior_hierarchy.get(series_code)
        window_prior_value = prior_entry[0] if prior_entry is not None else current_value
        if not has_history:
            # No publication history at all for this series: it starts at the
            # configured reference value (config/method.yaml) rather than an invented
            # base — CLAUDE.md principle 5, config over constants. This is the
            # *published* anchor splice() will scale from; it is not the window's own
            # internal-scale prior value computed above.
            bootstrap_series.add(series_code)
            published = pd.concat(
                [
                    published,
                    pd.DataFrame(
                        [
                            {
                                "series_code": series_code,
                                "period": prior_period,
                                "value": method.index_reference_value,
                            }
                        ]
                    ),
                ],
                ignore_index=True,
            )
        window_indices[series_code] = pd.Series(
            [window_prior_value, current_value], index=[prior_period, current_period]
        )
        coverage[series_code] = (n_quotes, coverage_pct)

    output = run_index(window_indices, published, coverage, method, str(snapshot_id), method_hash)

    index_value_rows: list[dict[str, Any]] = [
        {
            "index_run_id": index_run_row.id,
            "series_id": series_ids[series_code],
            "period": prior_period,
            "value": method.index_reference_value,
            "n_quotes": 0,
            "coverage_pct": None,
        }
        for series_code in sorted(bootstrap_series)
    ]
    for _, row in output.index_values.iterrows():
        coverage_pct = row["coverage_pct"]
        index_value_rows.append(
            {
                "index_run_id": index_run_row.id,
                "series_id": series_ids[row["series_code"]],
                "period": row["period"],
                "value": float(row["value"]),
                "n_quotes": int(row["n_quotes"]),
                "coverage_pct": float(coverage_pct) if coverage_pct is not None else None,
            }
        )
    session.execute(insert(IndexValue), index_value_rows)

    revision_rows: list[dict[str, Any]] = [
        {
            "id": uuid.uuid4(),
            "series_id": series_ids[series_code],
            "period": prior_period,
            "old_value": None,
            "new_value": float(method.index_reference_value),
            "reason": (
                "First publication of the reference period "
                f"({method.price_reference_period}), at the configured reference value."
            ),
            "revised_at": datetime.now(tz=UTC),
        }
        for series_code in sorted(bootstrap_series)
    ]
    revision_rows.extend(
        {
            "id": uuid.uuid4(),
            "series_id": series_ids[row["series_code"]],
            "period": row["period"],
            "old_value": float(row["old_value"]) if row["old_value"] is not None else None,
            "new_value": float(row["new_value"]),
            "reason": row["reason"],
            "revised_at": datetime.now(tz=UTC),
        }
        for _, row in output.revisions.iterrows()
    )
    # run_index() only ever logs a revision when it recomputes an *already-published*
    # period (see apix_core.index.run._publish_one_series and its own test suite,
    # TestFirstPublication.test_first_ever_run_of_a_series: revisions.empty by design).
    # A first-ever publication of a (series, period) is therefore not a revision in the
    # pure-math sense — but it is still the first entry in that period's public history,
    # so it is recorded here too, with old_value=null, exactly as /v1/index/revisions
    # documents ("First publications appear with old_value = null").
    already_published = set(zip(published["series_code"], published["period"], strict=False))
    revised_keys = set(
        zip(output.revisions["series_code"], output.revisions["period"], strict=False)
    )
    for _, row in output.index_values.iterrows():
        key = (row["series_code"], row["period"])
        if key in already_published or key in revised_keys:
            continue
        revision_rows.append(
            {
                "id": uuid.uuid4(),
                "series_id": series_ids[row["series_code"]],
                "period": row["period"],
                "old_value": None,
                "new_value": float(row["value"]),
                "reason": "First publication of the period.",
                "revised_at": datetime.now(tz=UTC),
            }
        )
    if revision_rows:
        session.execute(insert(RevisionLog), revision_rows)

    # Lineage for /v1/provenance's contributed_to: the headline series and each route
    # series this run published, linked to the clean rows that fed their current-period
    # cross-section. Carrier-type/advance-window breakdowns are not linked at this
    # granularity — their own audit path is /v1/index/contributors -> the route series,
    # which is linked.
    route_code_by_id: dict[uuid.UUID, str] = dict(
        session.execute(select(Route.id, Route.code)).tuples().all()
    )
    current_period_clean = persistable_clean.loc[
        (persistable_clean["query_date"] == as_of) & (~persistable_clean["is_outlier"])
    ]
    lineage_rows: list[dict[str, Any]] = []
    if _SERIES_HEADLINE in current_hierarchy:
        lineage_rows.extend(
            {
                "index_run_id": index_run_row.id,
                "series_id": series_ids[_SERIES_HEADLINE],
                "period": current_period,
                "clean_id": clean_id,
            }
            for clean_id in current_period_clean["clean_id"]
        )
    for route_id, group in current_period_clean.groupby("route_id"):
        series_code = f"APIX.ROUTE.{route_code_by_id.get(route_id)}.M"
        if series_code not in current_hierarchy:
            continue
        lineage_rows.extend(
            {
                "index_run_id": index_run_row.id,
                "series_id": series_ids[series_code],
                "period": current_period,
                "clean_id": clean_id,
            }
            for clean_id in group["clean_id"]
        )
    if lineage_rows:
        session.execute(insert(IndexValueQuote), lineage_rows)

    session.commit()

    return IndexRunPersistResult(
        index_run_id=index_run_row.id,
        snapshot_id=snapshot_id,
        vintage_date=as_of,
        period=current_period,
        published_series=sorted(current_hierarchy),
        skipped_series=sorted(set(prior_hierarchy) - set(current_hierarchy)),
        revision_count=len(revision_rows),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute and publish the APIx index for one date, from the database."
    )
    parser.add_argument("--date", type=date.fromisoformat, required=True, help="as-of date")
    parser.add_argument(
        "--days", type=int, default=21, help="trailing collection-day window feeding the estimate"
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="target database (default: APIX_DATABASE_SYNC_URL)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    database_url = args.database_url or settings.database_sync_url
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            result = compute_and_persist(session, args.date, args.days)
    finally:
        engine.dispose()

    log.info(
        "index_run_finished",
        as_of=result.vintage_date.isoformat(),
        period=result.period.isoformat(),
        index_run_id=str(result.index_run_id),
        snapshot_id=str(result.snapshot_id),
        published_series=result.published_series,
        skipped_series=result.skipped_series,
        revisions=result.revision_count,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via make index-run
    raise SystemExit(main())
