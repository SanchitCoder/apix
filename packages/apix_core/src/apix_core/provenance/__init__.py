"""Provenance: index value -> contributing quotes -> source, decision and raw bytes.

The contract is that the walk is always possible: no code path may produce a number
this package cannot trace (CLAUDE.md principle 1). :func:`stamp` writes the evidence
at collection time; :func:`resolve` reads the chain back for the API.
"""

from __future__ import annotations

from apix_core.provenance.hashing import hash_url, normalise_url, sha256_hex
from apix_core.provenance.resolve import (
    DecisionProvenance,
    ProvenanceChain,
    QuoteProvenance,
    RunProvenance,
    SourceProvenance,
    resolve,
)
from apix_core.provenance.stamp import RawResponse, stamp
from apix_core.provenance.store import (
    LocalObjectStore,
    ObjectStore,
    ProvenanceError,
    content_key,
)

__all__ = [
    "DecisionProvenance",
    "LocalObjectStore",
    "ObjectStore",
    "ProvenanceChain",
    "ProvenanceError",
    "QuoteProvenance",
    "RawResponse",
    "RunProvenance",
    "SourceProvenance",
    "content_key",
    "hash_url",
    "normalise_url",
    "resolve",
    "sha256_hex",
    "stamp",
]
