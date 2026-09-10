"""Regenerate docs/backtest.md — `make backtest`.

Unlike ``docs/plot_synthetic_curves.py`` (DB-free, plots the in-memory synthetic
generator), this script is database-backed: it scores real, published
``index_value`` rows (the ``APIX.ALL.M`` national series and every ``APIX.ROUTE.*.M``
series) against ``dgca_fare_reference`` rows loaded via ``make load-dgca-fares`` (see
docs/data-sources.md). As of most checkouts ``dgca_fare_reference`` is empty — the
report still generates, and says so honestly (``n_periods = 0`` for every scope, per
:func:`apix_core.backtest.score.score_apix_vs_dgca`'s own contract) rather than
failing or inventing a score. Re-run after loading real data for a real report.

``docs/backtest.md`` is generated, never hand-edited — the same rule
``docs/methodology.md`` follows.
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import structlog
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apix_core.backtest import BacktestScore, score_national_and_per_route
from apix_core.config import find_config_dir, load_backtest
from apix_core.models import DgcaFareReference, IndexValue, Route, Series
from apix_core.settings import get_settings

log = structlog.get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "docs" / "backtest"
DOC_PATH = REPO_ROOT / "docs" / "backtest.md"

_HEADLINE_SERIES = "APIX.ALL.M"


def _series_from_points(points: list[tuple[date, float]]) -> pd.Series:
    periods, values = zip(*sorted(points), strict=True)
    return pd.Series(values, index=pd.Index(list(periods), name="period"), dtype="float64")


def _load_apix_series(
    session: Session, window_start: date, window_end: date
) -> tuple[pd.Series, dict[str, pd.Series]]:
    """(national series, {route_code: series}) of published APIx values in the window."""
    rows = session.execute(
        select(Series.code, IndexValue.period, IndexValue.value)
        .join(IndexValue, IndexValue.series_id == Series.id)
        .where(IndexValue.period.between(window_start, window_end))
    ).all()
    national_points: list[tuple[date, float]] = []
    by_route_points: dict[str, list[tuple[date, float]]] = {}
    for code, period, value in rows:
        if code == _HEADLINE_SERIES:
            national_points.append((period, float(value)))
        elif code.startswith("APIX.ROUTE."):
            route_code = code.split(".")[2]
            by_route_points.setdefault(route_code, []).append((period, float(value)))
    national = (
        _series_from_points(national_points) if national_points else pd.Series(dtype="float64")
    )
    by_route = {code: _series_from_points(points) for code, points in by_route_points.items()}
    return national, by_route


def _load_dgca_reference(
    session: Session, window_start: date, window_end: date
) -> tuple[pd.Series, dict[str, pd.Series]]:
    """(national reference, {route_code: series}) of dgca_fare_reference in the window.

    The national reference is a simple mean across routes with loaded data for that
    period — NOT weighted by ``dgca_pax_share``, because ``config/basket.yaml``'s
    ``dgca_pax_share`` is null on every route as of this script's introduction (see
    docs/data-sources.md). Stated here, not hidden in the number.
    """
    rows = session.execute(
        select(Route.code, DgcaFareReference.period, DgcaFareReference.avg_fare)
        .join(Route, Route.id == DgcaFareReference.route_id)
        .where(DgcaFareReference.period.between(window_start, window_end))
    ).all()
    by_route_points: dict[str, list[tuple[date, float]]] = {}
    for route_code, period, avg_fare in rows:
        by_route_points.setdefault(route_code, []).append((period, float(avg_fare)))

    by_route: dict[str, pd.Series] = {}
    for route_code, points in by_route_points.items():
        frame = pd.DataFrame(points, columns=["period", "avg_fare"])
        by_route[route_code] = frame.groupby("period")["avg_fare"].mean()

    if by_route:
        combined = pd.concat(by_route.values(), axis=1)
        national = combined.mean(axis=1, skipna=True)
    else:
        national = pd.Series(dtype="float64")
    return national, by_route


def _chart_filename(scope: str) -> str:
    return f"{scope.replace('/', '_')}.png"


def _draw_chart(scope: str, apix: pd.Series, reference: pd.Series) -> None:
    aligned = (
        apix.rename("APIx")
        .to_frame()
        .join(reference.rename("DGCA reference"), how="inner")
        .dropna()
        .sort_index()
    )
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(aligned.index.astype(str), aligned["APIx"], marker="o", label="APIx")
    ax.plot(
        aligned.index.astype(str), aligned["DGCA reference"], marker="o", label="DGCA reference"
    )
    ax.set_title(f"APIx vs DGCA reference — {scope}")
    ax.set_xlabel("period")
    ax.set_ylabel("level")
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_DIR / _chart_filename(scope), dpi=120)
    plt.close(fig)


def _fmt(value: float | None, spec: str) -> str:
    return "—" if value is None else format(value, spec)


def _render_markdown(
    scores: list[BacktestScore], window_start: date, window_end: date, configured_window_days: int
) -> str:
    lines = [
        "# APIx back-test report",
        "",
        "GENERATED by `docs/generate_backtest_report.py` (`make backtest`). Do not hand-edit.",
        "",
        f"Configured reporting window: {configured_window_days} days "
        "(`config/backtest.yaml`'s `reporting_window_days`). "
        f"Actual window used: **{window_start.isoformat()} to {window_end.isoformat()}**.",
        "",
        "Scores published `index_value` rows against `dgca_fare_reference` rows "
        "(see `docs/data-sources.md`). As of most checkouts `dgca_fare_reference` is "
        "empty, so every scope below shows zero periods — that is the honest state of "
        "this repository's loaded data, not a bug in this report. Load real data with "
        "`make load-dgca-fares` and re-run `make backtest`.",
        "",
        "| Scope | Periods | Correlation | MAPE (%) | Directional accuracy (%) | Coverage note |",
        "|---|---|---|---|---|---|",
    ]
    for s in scores:
        lines.append(
            f"| {s.scope} | {s.n_periods} | {_fmt(s.correlation, '.3f')} | "
            f"{_fmt(s.mape, '.2f')} | {_fmt(s.directional_accuracy, '.1f')} | {s.coverage_note} |"
        )
    lines += ["", "## Charts", ""]
    charted = [s.scope for s in scores if s.n_periods >= 2]
    if charted:
        lines += [f"![{scope}](backtest/{_chart_filename(scope)})\n" for scope in charted]
    else:
        lines.append("No scope has at least 2 overlapping periods — no charts to draw.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate docs/backtest.md from real index_value vs dgca_fare_reference."
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=None,
        help="override config/backtest.yaml's reporting_window_days",
    )
    parser.add_argument(
        "--window-end",
        type=date.fromisoformat,
        default=None,
        help="window end date (default: today)",
    )
    parser.add_argument(
        "--database-url", default=None, help="target database (default: APIX_DATABASE_SYNC_URL)"
    )
    args = parser.parse_args(argv)

    backtest_cfg = load_backtest(find_config_dir())
    window_days = args.window_days or backtest_cfg.reporting_window_days
    window_end = args.window_end or datetime.now(tz=UTC).date()
    window_start = window_end - timedelta(days=window_days)

    settings = get_settings()
    database_url = args.database_url or settings.database_sync_url
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            apix_national, apix_by_route = _load_apix_series(session, window_start, window_end)
            dgca_national, dgca_by_route = _load_dgca_reference(session, window_start, window_end)
    finally:
        engine.dispose()

    scores = score_national_and_per_route(
        apix_national,
        dgca_national,
        apix_by_route,
        dgca_by_route,
        backtest_cfg.min_periods_for_correlation,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for score in scores:
        if score.n_periods < 2:
            continue
        is_national = score.scope == "national"
        apix_series = apix_national if is_national else apix_by_route[score.scope]
        reference_series = dgca_national if is_national else dgca_by_route[score.scope]
        _draw_chart(score.scope, apix_series, reference_series)

    DOC_PATH.write_text(
        _render_markdown(scores, window_start, window_end, window_days), encoding="utf-8"
    )
    log.info(
        "backtest_report_written",
        path=str(DOC_PATH),
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        scopes=[s.scope for s in scores],
        scored=[s.scope for s in scores if s.n_periods >= 2],
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via make backtest
    raise SystemExit(main())
