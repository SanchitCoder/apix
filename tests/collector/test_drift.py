from __future__ import annotations

import json

from apix_collector.drift import capture_drift, diff_shapes, flatten_keys


def test_flatten_keys_collapses_list_indices() -> None:
    payload = {"items": [{"a": 1}, {"a": 2, "b": 3}]}
    assert flatten_keys(payload) == {"items", "items[].a", "items[].b"}


def test_flatten_keys_handles_nested_objects() -> None:
    payload = {"dep": {"airport": "DEL", "dateTime": "x"}}
    assert flatten_keys(payload) == {"dep", "dep.airport", "dep.dateTime"}


def test_diff_shapes_reports_additions_and_removals() -> None:
    diff = diff_shapes(frozenset({"a", "b"}), frozenset({"b", "c"}))
    assert diff.added == frozenset({"c"})
    assert diff.removed == frozenset({"a"})
    assert not diff.is_empty


def test_diff_shapes_empty_when_identical() -> None:
    diff = diff_shapes(frozenset({"a"}), frozenset({"a"}))
    assert diff.is_empty


def test_capture_drift_writes_the_payload_and_reports_the_diff(tmp_path) -> None:
    payload = json.dumps({"a": 1, "c": 2}).encode("utf-8")
    report = capture_drift(
        "airline_test",
        payload,
        frozenset({"a", "b"}),
        tmp_path,
        reason="field b disappeared",
    )
    assert report.captured_path.is_file()
    assert report.captured_path.read_bytes() == payload
    assert report.captured_path.suffix == ".json"
    assert report.diff.added == frozenset({"c"})
    assert report.diff.removed == frozenset({"b"})
    assert report.reason == "field b disappeared"


def test_capture_drift_handles_non_json_payloads(tmp_path) -> None:
    payload = b"<html>not json</html>"
    report = capture_drift("ota_test", payload, frozenset(), tmp_path, reason="unexpected markup")
    assert report.captured_path.suffix == ".bin"
    assert report.captured_path.read_bytes() == payload
