"""``python -m apix_scheduler.nowcast_run`` — ``make nowcast-run DATE=... TARGET=...`` calls this.

Nowcasts the CPI air-fare item index for ``--target-period`` (a calendar month) using
the aggregated-regressor OLS bridge model (:mod:`apix_core.nowcast.bridge`).

**Precondition**: ``make index-run`` must already have published an ``index_value`` for
``--target-period`` at (or before) ``--date`` — this script does not build a
partial-month APIx aggregate itself. It does not need to: ``index_run.py``'s
``current_period`` is already exactly that concept (whatever data exists through
``as_of`` within the calendar month, published as that period's figure — see
``apix_scheduler.index_run.compute_and_persist``'s own docstring). Reusing it, rather
than building a second partial-month computation, is what keeps this script small and
keeps there being exactly one definition of "the APIx level right now".

Every regressor this script builds carries a ``collected_at`` bound (the ``index_run``
that published an APIx figure, or the row's insertion time for a CPI figure), and
:func:`apix_core.nowcast.bridge.fit_bridge_model` re-asserts vintage safety on top of
the bound already applied here — the same defense-in-depth
:mod:`apix_core.nowcast.vintage`'s own docstring describes. Insufficient history, a
missing target row, or a MIDAS config selection are all honest skips (logged, no
``nowcast_value`` row written), never a fabricated estimate — CLAUDE.md principle 2.
"""

from __future__ import annotations

import argparse
import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pandas as pd
import structlog
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apix_core.config import find_config_dir, load_nowcast
from apix_core.models import CpiAirfareIndex, IndexRun, IndexValue, NowcastValue, Series
from apix_core.nowcast.bridge import InsufficientHistoryError, fit_bridge_model
from apix_core.nowcast.vintage import VintageViolationError, filter_as_of
from apix_core.settings import get_settings

if TYPE_CHECKING:
    from apix_core.nowcast.bridge import BridgeModelResult

log = structlog.get_logger(__name__)

_HEADLINE_SERIES = "APIX.ALL.M"
_TARGET_SERIES = "CPI.AIRFARE.M"
_MODEL_VERSION = "ols_lagged-2026.1"


def _load_apix_monthly(session: Session) -> pd.DataFrame:
    """Every published national APIx figure, every vintage: ``period``,
    ``apix_value``, ``apix_collected_at`` (the ``index_run`` that produced it).
    """
    rows = session.execute(
        select(IndexValue.period, IndexValue.value, IndexRun.computed_at)
        .join(Series, Series.id == IndexValue.series_id)
        .join(IndexRun, IndexRun.id == IndexValue.index_run_id)
        .where(Series.code == _HEADLINE_SERIES)
    ).all()
    return pd.DataFrame(rows, columns=["period", "apix_value", "apix_collected_at"]).astype(
        {"apix_value": "float64"}
    )


def _load_cpi_monthly(session: Session) -> pd.DataFrame:
    """Every loaded CPI air-fare item index figure, every vintage: ``period``,
    ``cpi_value``, ``cpi_collected_at``.
    """
    rows = session.execute(
        select(CpiAirfareIndex.period, CpiAirfareIndex.value, CpiAirfareIndex.collected_at)
    ).all()
    return pd.DataFrame(rows, columns=["period", "cpi_value", "cpi_collected_at"]).astype(
        {"cpi_value": "float64"}
    )


def _latest_by_period_as_of(
    frame: pd.DataFrame, as_of: date, value_col: str, collected_col: str
) -> pd.DataFrame:
    """For each period, the latest vintage that was actually knowable by ``as_of`` —
    the vintage-safe collapse from "every release ever" down to "what a caller
    standing at ``as_of`` could have seen". Reuses
    :func:`apix_core.nowcast.vintage.filter_as_of` rather than re-implementing the
    bound.
    """
    columns = ["period", value_col, collected_col]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    available = filter_as_of(frame, as_of, timestamp_col=collected_col)
    if available.empty:
        return pd.DataFrame(columns=columns)
    return available.sort_values(collected_col).groupby("period", as_index=False).last()[columns]


def build_observations(session: Session, as_of: date) -> pd.DataFrame:
    """The full ``(period, apix_value, cpi_value, collected_at)`` frame
    :func:`apix_core.nowcast.bridge.fit_bridge_model` needs, bounded to ``as_of``.
    """
    apix = _latest_by_period_as_of(
        _load_apix_monthly(session), as_of, "apix_value", "apix_collected_at"
    )
    cpi = _latest_by_period_as_of(
        _load_cpi_monthly(session), as_of, "cpi_value", "cpi_collected_at"
    )
    if apix.empty:
        return pd.DataFrame(columns=["period", "apix_value", "cpi_value", "collected_at"])
    merged = apix.merge(cpi, on="period", how="left")
    merged["collected_at"] = merged[["apix_collected_at", "cpi_collected_at"]].max(
        axis=1, skipna=True
    )
    return merged[["period", "apix_value", "cpi_value", "collected_at"]]


def compute_and_persist(
    session: Session, as_of: date, target_period: date, model_version: str = _MODEL_VERSION
) -> NowcastValue | None:
    """Fit the bridge model and write one ``nowcast_value`` row, or log an honest skip
    and write nothing. ``make nowcast-run`` calls this.
    """
    nowcast_cfg = load_nowcast(find_config_dir())
    observations = build_observations(session, as_of)
    if observations.empty or target_period not in set(observations["period"]):
        log.info(
            "nowcast_run_skipped_no_target_row",
            as_of=as_of.isoformat(),
            target_period=target_period.isoformat(),
            reason="target period has no published APIx value as of this date — "
            "run `make index-run DATE=...` for this date first",
        )
        return None

    result: BridgeModelResult
    try:
        result = fit_bridge_model(
            observations, nowcast_cfg.bridge_model, target_period, as_of, model_version
        )
    except (
        InsufficientHistoryError,
        VintageViolationError,
        NotImplementedError,
        ValueError,
    ) as exc:
        log.info(
            "nowcast_run_skipped",
            as_of=as_of.isoformat(),
            target_period=target_period.isoformat(),
            reason=str(exc),
        )
        return None

    row = NowcastValue(
        id=uuid.uuid4(),
        target_series=_TARGET_SERIES,
        target_period=target_period,
        point_estimate=Decimal(str(round(result.point_estimate, 6))),
        ci_low=Decimal(str(round(result.ci_low, 6))),
        ci_high=Decimal(str(round(result.ci_high, 6))),
        model_version=model_version,
    )
    session.add(row)
    session.commit()
    log.info(
        "nowcast_run_published",
        as_of=as_of.isoformat(),
        target_period=target_period.isoformat(),
        point_estimate=result.point_estimate,
        ci_low=result.ci_low,
        ci_high=result.ci_high,
        n_obs=result.n_obs,
        r_squared=result.r_squared,
    )
    return row


def _parse_period(value: str) -> date:
    year_str, month_str = value.split("-")
    return date(int(year_str), int(month_str), 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Nowcast the CPI air-fare item index for one target period."
    )
    parser.add_argument("--date", type=date.fromisoformat, required=True, help="as-of date")
    parser.add_argument(
        "--target-period", type=_parse_period, required=True, help="target month, e.g. 2026-09"
    )
    parser.add_argument(
        "--database-url", default=None, help="target database (default: APIX_DATABASE_SYNC_URL)"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    database_url = args.database_url or settings.database_sync_url
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            compute_and_persist(session, args.date, args.target_period)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via make nowcast-run
    raise SystemExit(main())
