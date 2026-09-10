"""Vintage-safe filtering.

There is no separate "vintage store" table in this schema: point-in-time correctness
already comes from ``fare_quote.collected_at`` (append-only hypertable) and
``index_run.computed_at`` / ``index_value`` never being overwritten (a recompute is a
new row, not an update — see ``apix_core.models.index``). "Using the vintage store"
means filtering those existing append-only tables to what was actually available at a
given moment, and this module is exactly that filter, expressed as a pure function so
it can run with no database at all.

Look-ahead bias is the failure mode that would discredit the whole project (CLAUDE.md).
Anything that fits a model must pass its inputs through :func:`filter_as_of` first, and
:mod:`apix_core.nowcast.bridge` re-asserts the invariant itself rather than trusting a
caller to have filtered correctly upstream — defense in depth against exactly this
failure mode.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from datetime import date, datetime


class VintageViolationError(ValueError):
    """A row with a timestamp after the nowcast date reached a fit or filter call."""


def _comparable_timestamp(as_of: date | datetime, reference: pd.Series) -> pd.Timestamp:
    """``as_of`` as a :class:`pandas.Timestamp` matching ``reference``'s tz-awareness.

    A plain ``datetime.date``/``datetime.datetime`` compared directly against a
    tz-aware ``datetime64`` column raises ``TypeError`` in pandas rather than doing
    what a caller means — so every comparison in this module goes through here first.
    """
    ts = pd.Timestamp(as_of)
    is_tz_aware = isinstance(reference.dtype, pd.DatetimeTZDtype)
    if is_tz_aware and ts.tzinfo is None:
        return ts.tz_localize("UTC")
    if not is_tz_aware and ts.tzinfo is not None:
        return ts.tz_localize(None)
    return ts


def filter_as_of(
    df: pd.DataFrame, as_of: date | datetime, timestamp_col: str = "collected_at"
) -> pd.DataFrame:
    """Rows of ``df`` whose ``timestamp_col`` was available by ``as_of``, inclusive.

    Never raises on a clean input — an empty result for an ``as_of`` before any data
    existed is itself the honest, correct answer (CLAUDE.md principle 2: empty results
    are data, not gaps). Raises :class:`ValueError` only if ``timestamp_col`` is absent.
    """
    if timestamp_col not in df.columns:
        raise ValueError(f"filter_as_of: {timestamp_col!r} is not a column of the input")
    if df.empty:
        return df.copy()
    ts = _comparable_timestamp(as_of, df[timestamp_col])
    return df.loc[df[timestamp_col] <= ts].copy()


def assert_no_look_ahead(
    df: pd.DataFrame, as_of: date | datetime, timestamp_col: str = "collected_at"
) -> None:
    """Raise :class:`VintageViolationError` if any row of ``df`` is later than ``as_of``.

    Called by every fitting function in this package before it touches the data — the
    guard that makes the look-ahead test meaningful even if a caller's own SQL-level
    filter is wrong or missing.
    """
    if timestamp_col not in df.columns:
        raise ValueError(f"assert_no_look_ahead: {timestamp_col!r} is not a column of the input")
    if df.empty:
        return
    ts = _comparable_timestamp(as_of, df[timestamp_col])
    offending = df.loc[df[timestamp_col] > ts]
    if not offending.empty:
        latest = offending[timestamp_col].max()
        raise VintageViolationError(
            f"{len(offending)} row(s) have {timestamp_col} after as_of={as_of} "
            f"(latest: {latest}) — a nowcast may only be fitted on data that was "
            f"actually available at the time"
        )


__all__ = ["VintageViolationError", "assert_no_look_ahead", "filter_as_of"]
