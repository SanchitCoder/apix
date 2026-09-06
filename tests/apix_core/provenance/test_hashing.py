"""URL normalisation and hashing: two spellings of one URL must hash identically."""

from __future__ import annotations

import hashlib

import pytest

from apix_core.provenance.hashing import hash_url, normalise_url, sha256_hex


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://Example.ORG/fares", "https://example.org/fares"),
        ("https://example.org:443/fares", "https://example.org/fares"),
        ("http://example.org:80/fares", "http://example.org/fares"),
        ("http://example.org:8080/fares", "http://example.org:8080/fares"),
        ("https://example.org", "https://example.org/"),
        ("https://example.org/x?b=2&a=1", "https://example.org/x?a=1&b=2"),
        ("https://example.org/x?a=1#section", "https://example.org/x?a=1"),
        ("https://example.org/x?flag=&a=1", "https://example.org/x?a=1&flag="),
        # Path and value case is meaning, not noise.
        ("https://example.org/Fares?from=DEL", "https://example.org/Fares?from=DEL"),
    ],
)
def test_normalise_url(raw, expected):
    assert normalise_url(raw) == expected


def test_equivalent_urls_hash_identically():
    assert hash_url("HTTPS://Example.org:443/x?b=2&a=1#f") == hash_url(
        "https://example.org/x?a=1&b=2"
    )


def test_different_urls_hash_differently():
    assert hash_url("https://example.org/x?from=DEL") != hash_url("https://example.org/x?from=BOM")


def test_sha256_hex_matches_the_standard_library():
    payload = b"raw response body"
    assert sha256_hex(payload) == hashlib.sha256(payload).hexdigest()
    assert len(sha256_hex(b"")) == 64
