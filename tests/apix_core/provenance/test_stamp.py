"""stamp(): a quote leaves collection carrying its full evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from apix_core.models.quotes import FareQuote
from apix_core.provenance import LocalObjectStore, hash_url, stamp

BODY = b'{"fare": {"total": 4999, "currency": "INR"}}'
URL = "HTTPS://Example.test:443/fares/DEL-BOM?date=2026-09-10"


@dataclass
class FakeResponse:
    """Anything with .url and .content is stampable — httpx never enters here."""

    url: str
    content: bytes


def test_stamp_sets_all_three_provenance_fields(tmp_path):
    store = LocalObjectStore(tmp_path)
    quote = FareQuote()
    response = FakeResponse(url=URL, content=BODY)

    result = stamp(quote, response, store)

    assert result is quote  # chains
    assert quote.source_url_hash == hash_url(URL)
    assert quote.content_hash == hashlib.sha256(BODY).hexdigest()
    assert quote.raw_payload_ref is not None
    # The ref resolves to the exact bytes that were hashed.
    assert store.get(quote.raw_payload_ref) == BODY


def test_url_hash_is_of_the_normalised_url(tmp_path):
    store = LocalObjectStore(tmp_path)
    a = stamp(FareQuote(), FakeResponse(url=URL, content=BODY), store)
    b = stamp(
        FareQuote(),
        FakeResponse(url="https://example.test/fares/DEL-BOM?date=2026-09-10", content=BODY),
        store,
    )
    assert a.source_url_hash == b.source_url_hash


def test_identical_bodies_share_one_stored_payload(tmp_path):
    store = LocalObjectStore(tmp_path)
    a = stamp(FareQuote(), FakeResponse(url=URL, content=BODY), store)
    b = stamp(FareQuote(), FakeResponse(url=URL + "&t=2", content=BODY), store)
    assert a.raw_payload_ref == b.raw_payload_ref
    assert a.content_hash == b.content_hash
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert len(files) == 1
