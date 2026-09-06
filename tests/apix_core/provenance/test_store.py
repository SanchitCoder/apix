"""LocalObjectStore: content-addressed, idempotent, and tamper-evident."""

from __future__ import annotations

import hashlib

import pytest

from apix_core.provenance.store import LocalObjectStore, ProvenanceError, content_key


def test_key_is_derived_from_content():
    body = b"<html>fare page</html>"
    digest = hashlib.sha256(body).hexdigest()
    assert content_key(body) == f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"


def test_put_get_roundtrip(tmp_path):
    store = LocalObjectStore(tmp_path)
    body = b"raw response bytes \x00\xff"
    ref = store.put(body)
    assert store.get(ref) == body
    assert (tmp_path / ref).is_file()


def test_put_is_idempotent(tmp_path):
    store = LocalObjectStore(tmp_path)
    body = b"same bytes"
    assert store.put(body) == store.put(body)
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert len(files) == 1


def test_missing_ref_raises(tmp_path):
    store = LocalObjectStore(tmp_path)
    with pytest.raises(ProvenanceError, match="not found"):
        store.get("sha256/de/ad/" + "de" * 32)


def test_tampered_payload_is_detected(tmp_path):
    """A payload that no longer matches its content address is corruption, loudly."""
    store = LocalObjectStore(tmp_path)
    ref = store.put(b"original bytes")
    (tmp_path / ref).write_bytes(b"tampered bytes")
    with pytest.raises(ProvenanceError, match="content address"):
        store.get(ref)


def test_no_stray_tmp_files_left_behind(tmp_path):
    store = LocalObjectStore(tmp_path)
    store.put(b"a body")
    assert list(tmp_path.rglob("*.tmp")) == []
