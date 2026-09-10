"""Back-test harness: scoring APIx against a published reference fare series.

Pure function, no I/O — DataFrames/Series in, a :class:`~apix_core.backtest.score.BacktestScore`
out. ``docs/generate_backtest_report.py`` is the DB-backed caller that loads real
``index_value`` and ``dgca_fare_reference`` rows and writes ``docs/backtest.md``.
"""

from __future__ import annotations

from apix_core.backtest.score import BacktestScore, score_apix_vs_dgca, score_national_and_per_route

__all__ = ["BacktestScore", "score_apix_vs_dgca", "score_national_and_per_route"]
