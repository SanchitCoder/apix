from __future__ import annotations

import urllib.error
import urllib.request

import pytest

from apix_collector.fixtureserver import FixtureServer


def test_serves_a_real_fixture_file(repo_root) -> None:
    with FixtureServer(repo_root / "fixtures") as server:
        with urllib.request.urlopen(f"{server.base_url}/airline_indigo/DEL-BOM.json") as resp:  # noqa: S310
            assert resp.status == 200
            assert resp.headers["Content-Type"] == "application/json"
            body = resp.read()
        assert (repo_root / "fixtures" / "airline_indigo" / "DEL-BOM.json").read_bytes() == body


def test_404s_on_a_missing_fixture(repo_root) -> None:
    with (
        FixtureServer(repo_root / "fixtures") as server,
        pytest.raises(urllib.error.HTTPError) as excinfo,
    ):
        urllib.request.urlopen(f"{server.base_url}/airline_indigo/NOPE.json")  # noqa: S310
    assert excinfo.value.code == 404


def test_only_fixtures_paths_are_served(repo_root) -> None:
    with FixtureServer(repo_root / "fixtures") as server:
        root = server.base_url.removesuffix("/fixtures")
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(f"{root}/etc/passwd")  # noqa: S310
    assert excinfo.value.code == 404


def test_path_traversal_is_refused(repo_root) -> None:
    with (
        FixtureServer(repo_root / "fixtures") as server,
        pytest.raises(urllib.error.HTTPError) as excinfo,
    ):
        urllib.request.urlopen(f"{server.base_url}/../CLAUDE.md")  # noqa: S310
    assert excinfo.value.code in (403, 404)
