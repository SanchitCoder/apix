"""Cursor pagination. A cursor is opaque, but it is not magic."""

from __future__ import annotations

import pytest

from apix_api.pagination import CursorError, decode_cursor, encode_cursor, query_signature


def test_cursor_round_trips() -> None:
    sig = query_signature(series="APIX.ALL.M", freq="M")
    cursor = encode_cursor({"period": "2026-08-01"}, sig)
    assert decode_cursor(cursor, sig) == {"period": "2026-08-01"}


def test_cursor_from_a_different_query_is_rejected() -> None:
    """Reusing a cursor against changed filters must fail, not silently skip rows."""
    cursor = encode_cursor({"period": "2026-08-01"}, query_signature(series="A"))
    with pytest.raises(CursorError, match="different query"):
        decode_cursor(cursor, query_signature(series="B"))


@pytest.mark.parametrize("bad", ["", "not-base64!!", "eyJ4IjoxfQ"])
def test_malformed_cursors_are_rejected(bad: str) -> None:
    with pytest.raises(CursorError):
        decode_cursor(bad, query_signature(series="A"))


def test_signature_is_order_independent() -> None:
    assert query_signature(a=1, b=2) == query_signature(b=2, a=1)


def test_signature_changes_with_the_filters() -> None:
    assert query_signature(series="A") != query_signature(series="B")


def test_cursor_is_url_safe() -> None:
    cursor = encode_cursor({"code": "DEL-BOM"}, query_signature(x=1))
    assert "+" not in cursor
    assert "/" not in cursor
    assert "=" not in cursor
