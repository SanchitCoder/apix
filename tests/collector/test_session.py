from __future__ import annotations

import pytest

from apix_collector.session import SessionRotator


def test_rotates_through_the_pool() -> None:
    rotator = SessionRotator(pool_size=2)
    first = rotator.next()
    second = rotator.next()
    third = rotator.next()
    assert first.session_id != second.session_id
    assert first.session_id == third.session_id  # wrapped around


def test_headers_identify_the_session() -> None:
    rotator = SessionRotator(pool_size=1)
    ctx = rotator.next()
    assert ctx.headers["X-APIx-Session"] == ctx.session_id


def test_pool_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="pool_size"):
        SessionRotator(pool_size=0)
