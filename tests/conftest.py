"""Shared test fixtures.

Two rules govern everything in here:

* No test touches the live internet (CLAUDE.md guardrail). There is no fixture that
  makes an outbound request, and none should be added.
* Tests that need real infrastructure use throwaway containers and skip cleanly when no
  container runtime is present, so ``make test`` is meaningful on a laptop and complete
  in CI.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]


def _docker_available() -> bool:
    """Whether a usable container runtime is on PATH and responding."""
    if shutil.which("docker") is None:
        return False
    import subprocess

    try:
        return (
            subprocess.run(
                ["docker", "info"],  # noqa: S607 — resolved via PATH, checked above
                capture_output=True,
                timeout=10,
                check=False,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


DOCKER_AVAILABLE = _docker_available()

requires_docker = pytest.mark.skipif(
    not DOCKER_AVAILABLE,
    reason="no container runtime available; run `make test-integration` where one is",
)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def config_dir(repo_root: Path) -> Path:
    """The real ``config/`` directory. Tests validate the shipped files, not copies."""
    return repo_root / "config"


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    """An empty config directory for tests that write deliberately invalid files."""
    directory = tmp_path / "config"
    directory.mkdir()
    return directory


@pytest.fixture
def api_client() -> Iterator[TestClient]:
    """A TestClient over the real application, with lifespan startup run."""
    # Imported here so collecting the suite does not pay FastAPI's import cost.
    from fastapi.testclient import TestClient

    from apix_api.main import create_app

    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def fake_redis() -> Iterator[Any]:
    """An in-process Redis. Never a real server, never a network socket."""
    import fakeredis

    server = fakeredis.FakeStrictRedis(decode_responses=True)
    try:
        yield server
    finally:
        server.flushall()
        server.close()


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """A throwaway TimescaleDB, torn down at the end of the session.

    Skips when no container runtime is available. The image is the same one compose
    uses, so the hypertable path in migration 0001 is genuinely exercised rather than
    silently falling back to a plain table.
    """
    if not DOCKER_AVAILABLE:
        pytest.skip("no container runtime available")

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        "timescale/timescaledb:2.17.2-pg16",
        username="apix",
        password="apix",  # throwaway container, discarded at end of session
        dbname="apix_test",
    ) as container:
        yield container.get_connection_url()
