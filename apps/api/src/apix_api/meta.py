"""Build a real ``ResponseMeta`` block. The ``apix_api.examples`` helper of the same
shape stays EXAMPLE_ONLY-labelled on purpose; this is its database-backed counterpart.
"""

from __future__ import annotations

from datetime import UTC, datetime

from apix_api.pagination import ResponseMeta


def build_meta(
    *,
    data_status: str = "PUBLISHED",
    method_version: str | None = None,
    basket_version: str | None = None,
    index_run_id: str | None = None,
    snapshot_id: str | None = None,
) -> ResponseMeta:
    return ResponseMeta(
        data_status=data_status,
        generated_at=datetime.now(tz=UTC).isoformat(),
        method_version=method_version,
        basket_version=basket_version,
        index_run_id=index_run_id,
        snapshot_id=snapshot_id,
    )


__all__ = ["build_meta"]
