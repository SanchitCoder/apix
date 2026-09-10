"""Reproducibility: turning already-computed window index levels into the rows
``apix_scheduler`` persists as ``index_run``, ``index_value`` and ``revision_log`` —
CLAUDE.md principle 4.

Nothing here touches a database, the clock, or a random number generator. That is what
makes the reproducibility contract provable rather than merely intended: given the same
``data_snapshot_id``, the same ``method_config_hash``, and the same window index levels
(themselves already pure — :mod:`apix_core.index.multilateral`,
:mod:`apix_core.index.aggregate`), :func:`run_index` returns byte-identical output on
every call. ``tests/apix_core/index/test_run.py`` asserts this directly. Series are
iterated in sorted order specifically so that no dict/set ordering can make two
otherwise-identical calls diverge.

``run_index`` does not itself run the elementary/multilateral/hierarchy pipeline — that
composition is the caller's job (``apix_scheduler``), because it is the caller who
knows how to assemble a window's panel from the database. This module's job starts once
that pipeline has produced, for each published series, this window's own index level
series (see :func:`apix_core.index.splice.splice`) — and ends with the exact rows to
write, in one transaction, without ever revising an already-published value except by
recording the change in ``revision_log``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from apix_core.index.splice import splice
from apix_core.provenance.hashing import sha256_hex

if TYPE_CHECKING:
    from collections.abc import Mapping

    from apix_core.config.method import MethodConfigFile

INDEX_VALUE_COLUMNS = ("series_code", "period", "value", "n_quotes", "coverage_pct")
REVISION_COLUMNS = ("series_code", "period", "old_value", "new_value", "reason")

# Below this relative tolerance, a recomputed value is treated as the same number
# (floating-point noise), not a revision worth recording.
_REVISION_RELATIVE_TOLERANCE = 1e-9


def run_hash(data_snapshot_id: str, method_config_hash: str) -> str:
    """The reproducibility key. Two calls with the same key must be byte-identical."""
    return sha256_hex(f"{data_snapshot_id}|{method_config_hash}".encode())


@dataclass(frozen=True)
class IndexRunOutput:
    """Everything one index run writes, in the shape its tables expect.

    ``index_values`` and ``revisions`` are keyed by ``series_code`` rather than the
    database's ``series_id``/``index_run_id`` UUIDs — resolving a code to a UUID is a
    database lookup, which does not belong in a pure function. The caller does that
    resolution at write time, inside the same transaction.
    """

    run_hash: str
    index_values: pd.DataFrame
    revisions: pd.DataFrame


def _publish_one_series(
    series_code: str,
    window_index: pd.Series,
    published: pd.Series,
    method: object,
) -> tuple[object, float, dict[str, object] | None]:
    if window_index.empty:
        raise ValueError(f"{series_code}: window_index must have at least one period")
    if (window_index <= 0).any():
        raise ValueError(f"{series_code}: window index levels must be strictly positive")
    newest_period = window_index.index[-1]

    prior_periods = window_index.index[:-1]
    have_prior_published = len(published) > 0 and all(p in published.index for p in prior_periods)

    if len(window_index) == 1 or not have_prior_published:
        # Nothing to splice onto yet: this is the series' first-ever publication (or
        # the window has only the new period). The window's own level, relative to its
        # own base, is the publication outright.
        new_value = float(window_index.iloc[-1] / window_index.iloc[0])
    else:
        new_value = splice(method, published, window_index)  # type: ignore[arg-type]

    revision: dict[str, object] | None = None
    if newest_period in published.index:
        old_value = float(published.loc[newest_period])
        if abs(new_value - old_value) > _REVISION_RELATIVE_TOLERANCE * max(1.0, abs(old_value)):
            revision = {
                "series_code": series_code,
                "period": newest_period,
                "old_value": old_value,
                "new_value": new_value,
                "reason": "recomputed under the same (snapshot, config) key",
            }
    return newest_period, new_value, revision


def run_index(
    window_indices: Mapping[str, pd.Series],
    published: pd.DataFrame,
    coverage: Mapping[str, tuple[int, float]],
    config: MethodConfigFile,
    data_snapshot_id: str,
    method_config_hash: str,
) -> IndexRunOutput:
    """Publish the newest period of every series in ``window_indices``.

    * ``window_indices``: ``series_code -> pd.Series`` indexed by period, chronological,
      this window's own multilateral/aggregate index level (any consistent
      normalisation — see :mod:`apix_core.index.splice`). The *last* entry is the
      period being published; every earlier entry must already be a published period
      for ``config.splice_method`` to have something to splice onto (a brand-new series
      is exempt — see :func:`_publish_one_series`).
    * ``published``: columns ``series_code``, ``period``, ``value`` — the full known
      publication history. Empty on the very first run ever.
    * ``coverage``: ``series_code -> (n_quotes, coverage_pct)`` for the newest period.
    * ``config``: the validated method configuration; only ``splice_method`` is used
      here (the elementary/multilateral/hedonic choices already shaped
      ``window_indices`` upstream).

    Returns rows shaped for ``index_value`` and ``revision_log``, plus the
    :func:`run_hash` that stamps this run. Iterates series in sorted order and performs
    no I/O, so the result is a pure, deterministic function of its arguments.
    """
    if not window_indices:
        raise ValueError("window_indices must not be empty")
    missing_coverage = sorted(set(window_indices) - set(coverage))
    if missing_coverage:
        raise ValueError(f"coverage is missing entries for series: {missing_coverage}")

    value_rows: list[dict[str, object]] = []
    revision_rows: list[dict[str, object]] = []

    for series_code in sorted(window_indices):
        window_index = window_indices[series_code]
        prior = (
            published.loc[published["series_code"] == series_code]
            .set_index("period")["value"]
            .sort_index()
        )
        period, value, revision = _publish_one_series(
            series_code, window_index, prior, config.splice_method
        )
        n_quotes, coverage_pct = coverage[series_code]
        value_rows.append(
            {
                "series_code": series_code,
                "period": period,
                "value": value,
                "n_quotes": n_quotes,
                "coverage_pct": coverage_pct,
            }
        )
        if revision is not None:
            revision_rows.append(revision)

    index_values = pd.DataFrame(value_rows, columns=list(INDEX_VALUE_COLUMNS))
    revisions = pd.DataFrame(revision_rows, columns=list(REVISION_COLUMNS))
    return IndexRunOutput(
        run_hash=run_hash(data_snapshot_id, method_config_hash),
        index_values=index_values,
        revisions=revisions,
    )


__all__ = ["INDEX_VALUE_COLUMNS", "REVISION_COLUMNS", "IndexRunOutput", "run_hash", "run_index"]
