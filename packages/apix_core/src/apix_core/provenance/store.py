"""Content-addressed object storage for raw response bodies.

A quote's ``raw_payload_ref`` points here. Keys are derived from the body's own
SHA-256, so storage is idempotent, a ref can never point at the wrong bytes, and an
auditor can verify a payload against its quote's ``content_hash`` by inspection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from apix_core.provenance.hashing import sha256_hex

if TYPE_CHECKING:
    from pathlib import Path


class ProvenanceError(RuntimeError):
    """A provenance chain could not be written or resolved. Never swallowed."""


class ObjectStore(Protocol):
    """Anything that can hold raw payloads under content-addressed keys."""

    def put(self, body: bytes) -> str:
        """Store ``body``; return the content-addressed key to record as the ref."""
        ...

    def get(self, ref: str) -> bytes:
        """Return the exact bytes ``ref`` points at, or raise :class:`ProvenanceError`."""
        ...


def content_key(body: bytes) -> str:
    """The canonical key for ``body``: ``sha256/<aa>/<bb>/<full hash>``.

    Fanned out over two prefix levels so a filesystem-backed store never puts
    millions of files in one directory.
    """
    digest = sha256_hex(body)
    return f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"


class LocalObjectStore:
    """Filesystem-backed store — local runs and tests.

    The layout under ``root`` mirrors the key, so the same refs stay valid verbatim
    when the backend moves to a bucket.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def put(self, body: bytes) -> str:
        key = content_key(body)
        path = self._root / key
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write-then-rename so a crash mid-write cannot leave a truncated payload
            # sitting at a valid content-addressed key.
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(body)
            tmp.rename(path)
        return key

    def get(self, ref: str) -> bytes:
        path = self._root / ref
        if not path.is_file():
            raise ProvenanceError(f"raw payload ref {ref!r} not found under {self._root}")
        body = path.read_bytes()
        if content_key(body) != ref:
            raise ProvenanceError(
                f"raw payload at {ref!r} does not match its content address; "
                "the store has been tampered with or corrupted"
            )
        return body


__all__ = ["LocalObjectStore", "ObjectStore", "ProvenanceError", "content_key"]
