"""Self-healing hook: capture a drifted payload and make the failure loud.

When a mapper's expected shape stops matching what a source actually sends — a
renamed field, a restructured response, a new required key — this is the only
response: write the offending payload next to a diff against the last known-good
shape, and emit one structured, greppable log line. Nothing here repairs the mapper.
That is deliberate: an automatic "best guess" fix is exactly the kind of silent
failure CLAUDE.md forbids in a system that produces an official statistic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

_log = structlog.get_logger(__name__)


def flatten_keys(payload: Any, prefix: str = "") -> set[str]:
    """The set of key-paths in a JSON-like structure.

    List elements are collapsed to one ``[]`` segment so that "the third itinerary
    lost a field" and "the first itinerary lost a field" are the same shape change,
    not two. This is a structural fingerprint, not a full JSON Schema — good enough to
    say "a field appeared or disappeared", which is what drift detection needs.
    """
    keys: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            keys.add(path)
            keys |= flatten_keys(value, path)
    elif isinstance(payload, list):
        item_prefix = f"{prefix}[]"
        for item in payload:
            keys |= flatten_keys(item, item_prefix)
    return keys


@dataclass(frozen=True, slots=True)
class ShapeDiff:
    """What changed between a known-good shape and an offending payload."""

    added: frozenset[str]
    removed: frozenset[str]

    @property
    def is_empty(self) -> bool:
        return not self.added and not self.removed


def diff_shapes(known_good_keys: frozenset[str], actual_keys: frozenset[str]) -> ShapeDiff:
    return ShapeDiff(
        added=frozenset(actual_keys - known_good_keys),
        removed=frozenset(known_good_keys - actual_keys),
    )


@dataclass(frozen=True, slots=True)
class DriftReport:
    """Where the offending payload was captured, and what changed."""

    source_code: str
    captured_path: Path
    diff: ShapeDiff
    reason: str


def capture_drift(
    source_code: str,
    payload: bytes,
    known_good_keys: frozenset[str],
    drift_dir: Path,
    *,
    reason: str,
    clock: type[datetime] = datetime,
) -> DriftReport:
    """Write ``payload`` under ``drift_dir/<source_code>/`` and log a structured alert.

    Returns the report; the caller (a mapper) is expected to raise
    :class:`apix_collector.errors.SchemaDriftError` immediately after — this function
    only makes the drift visible, it never decides what happens next.
    """
    try:
        actual_keys: frozenset[str] = frozenset(flatten_keys(json.loads(payload)))
        suffix = ".json"
    except (json.JSONDecodeError, UnicodeDecodeError):
        actual_keys = frozenset()
        suffix = ".bin"

    diff = diff_shapes(known_good_keys, actual_keys)
    timestamp = clock.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target_dir = drift_dir / source_code
    target_dir.mkdir(parents=True, exist_ok=True)
    captured_path = target_dir / f"{timestamp}{suffix}"
    captured_path.write_bytes(payload)

    _log.error(
        "collector_schema_drift",
        source=source_code,
        reason=reason,
        captured_path=str(captured_path),
        keys_added=sorted(diff.added),
        keys_removed=sorted(diff.removed),
    )
    return DriftReport(
        source_code=source_code, captured_path=captured_path, diff=diff, reason=reason
    )


__all__ = ["DriftReport", "ShapeDiff", "capture_drift", "diff_shapes", "flatten_keys"]
