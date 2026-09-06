"""URL normalisation and content hashing.

``source_url_hash`` on a fare quote and ``url_hash`` on a policy decision are computed
here, from the same normal form, so that a quote can always be joined back to the
decision that authorised its collection. Two spellings of the same URL must hash
identically or the provenance chain silently breaks.
"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalise_url(url: str) -> str:
    """Canonical form of ``url``: what gets hashed, never what gets fetched.

    Lower-cases the scheme and host, drops a default port and the fragment, ensures a
    non-empty path, and sorts query parameters. Values and paths keep their case —
    ``?from=DEL`` and ``?from=del`` are different queries.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host if port is None or _DEFAULT_PORTS.get(scheme) == port else f"{host}:{port}"
    path = parts.path or "/"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((scheme, netloc, path, query, ""))


def sha256_hex(payload: bytes) -> str:
    """Hex SHA-256 of ``payload``."""
    return hashlib.sha256(payload).hexdigest()


def hash_url(url: str) -> str:
    """SHA-256 of the normalised URL — the value stored in ``source_url_hash``."""
    return sha256_hex(normalise_url(url).encode("utf-8"))


__all__ = ["hash_url", "normalise_url", "sha256_hex"]
