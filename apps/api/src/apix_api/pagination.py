"""Cursor pagination.

Every list endpoint is paginated the same way, with an opaque cursor.

The cursor is base64url of a compact JSON object holding the sort key of the last item
returned, plus the hash of the query it belongs to. It is opaque *by contract* — a
client must treat it as a token and pass it back unmodified — but it is deliberately
inspectable by an operator debugging a paging bug, and it carries ``q`` so that reusing
a cursor against a different filter is a 400 rather than silently wrong data.

Offset pagination is not offered: the series tables grow continuously, and a page
number over a moving result set produces duplicated and skipped rows.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000


class CursorError(ValueError):
    """Raised when a cursor is malformed or belongs to a different query."""


def encode_cursor(position: dict[str, Any], query_signature: str) -> str:
    """Encode a sort position into an opaque cursor string."""
    payload = {"p": position, "q": query_signature}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str, query_signature: str) -> dict[str, Any]:
    """Decode a cursor, rejecting one issued for a different query."""
    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding)
        payload = json.loads(raw)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CursorError("cursor is not a valid APIx cursor") from exc
    if not isinstance(payload, dict) or "p" not in payload or "q" not in payload:
        raise CursorError("cursor is not a valid APIx cursor")
    if payload["q"] != query_signature:
        raise CursorError(
            "cursor was issued for a different query; restart paging without a cursor"
        )
    position: dict[str, Any] = payload["p"]
    return position


def query_signature(**params: Any) -> str:
    """Stable short hash of the filter parameters a cursor is bound to."""
    canonical = json.dumps(
        {k: (v if v is None else str(v)) for k, v in sorted(params.items())},
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class PageInfo(BaseModel):
    """Paging state returned with every list response."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(description="Maximum items requested for this page.")
    returned: int = Field(description="Items actually returned.")
    has_more: bool = Field(description="Whether a further page exists.")
    next_cursor: str | None = Field(
        default=None,
        description=(
            "Opaque token. Pass it unchanged as the `cursor` query parameter to fetch "
            "the next page. Null when `has_more` is false. Cursors are bound to the "
            "filter parameters of the request that produced them."
        ),
    )


class Page[ItemT](BaseModel):
    """A page of results, with paging state and response metadata."""

    model_config = ConfigDict(extra="forbid")

    items: list[ItemT]
    pagination: PageInfo
    meta: ResponseMeta


class ResponseMeta(BaseModel):
    """Metadata attached to every APIx response.

    ``data_status`` is not decoration. Until Phase 3 wires the database in, every
    endpoint returns ``EXAMPLE_ONLY``: the shape is real, the numbers are placeholders
    and are labelled as such so that nothing downstream can mistake them for published
    statistics.
    """

    model_config = ConfigDict(extra="forbid")

    data_status: str = Field(
        default="EXAMPLE_ONLY",
        description=(
            "EXAMPLE_ONLY | PROVISIONAL | PUBLISHED | REVISED. EXAMPLE_ONLY means the "
            "payload is a contract placeholder and carries no statistical meaning."
        ),
    )
    generated_at: str = Field(description="RFC 3339 timestamp at which this response was built.")
    method_version: str | None = Field(
        default=None, description="Version of config/method.yaml behind these numbers."
    )
    basket_version: str | None = Field(
        default=None, description="Version of config/basket.yaml behind these numbers."
    )
    index_run_id: str | None = Field(
        default=None, description="The index_run that produced these values."
    )
    snapshot_id: str | None = Field(
        default=None, description="The data_snapshot the index_run consumed."
    )


Page.model_rebuild()


# Shared query parameters, so every list endpoint documents pagination identically.
CursorParam = Annotated[
    str | None,
    Query(
        description="Opaque cursor from a previous response's `pagination.next_cursor`.",
        examples=["eyJwIjp7InBlcmlvZCI6IjIwMjYtMDYtMDEifSwicSI6ImExYjJjM2Q0ZTVmNiJ9"],
    ),
]
LimitParam = Annotated[
    int,
    Query(
        ge=1,
        le=MAX_PAGE_SIZE,
        description=f"Page size. Default {DEFAULT_PAGE_SIZE}, maximum {MAX_PAGE_SIZE}.",
    ),
]
