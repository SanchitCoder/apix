"""Stamping a quote with its provenance at collection time.

Called by the collector for every quote, before the quote is persisted. After
:func:`stamp`, the row carries everything needed to walk back from a published index
value to the exact bytes the source served — CLAUDE.md principle 1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from apix_core.provenance.hashing import hash_url, sha256_hex

if TYPE_CHECKING:
    from apix_core.models.quotes import FareQuote
    from apix_core.provenance.store import ObjectStore


class RawResponse(Protocol):
    """The two things a response must expose to be stampable.

    ``httpx.Response`` satisfies this structurally; so does a replayed fixture. The
    protocol exists so this module never has to import an HTTP client — only
    ``apix_core.policy`` may do that.
    """

    @property
    def url(self) -> object:
        """The URL the response was served from; ``str()`` is applied to it."""
        ...

    @property
    def content(self) -> bytes:
        """The raw, undecoded response body."""
        ...


def stamp(quote: FareQuote, response: RawResponse, store: ObjectStore) -> FareQuote:
    """Set ``source_url_hash``, ``content_hash`` and ``raw_payload_ref`` on ``quote``.

    The body is written to the object store first: if the write fails, the quote is
    left unstamped and unpersistable rather than pointing at bytes that were never
    saved. Returns the same quote for chaining.
    """
    body = response.content
    quote.raw_payload_ref = store.put(body)
    quote.source_url_hash = hash_url(str(response.url))
    quote.content_hash = sha256_hex(body)
    return quote


__all__ = ["RawResponse", "stamp"]
