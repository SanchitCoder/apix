"""Shared fixtures for the collector test suite.

Every test in this package builds a *real* ``PolicyEngine`` (against fakeredis) and a
real, loopback-only ``FixtureServer`` — no ``httpx.MockTransport``, no stubbed
policy decisions. The point of ``apix_collector`` is that it goes through the real
compliance engine; a test that mocked that away would not be testing the thing that
matters.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from apix_collector.fixtureserver import FixtureServer
from apix_core.config import load_sources
from apix_core.policy import InMemoryDecisionLog, PolicyEngine

FIXTURES_ROOT = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def fixture_server() -> Iterator[FixtureServer]:
    with FixtureServer(FIXTURES_ROOT) as server:
        yield server


@pytest.fixture
def decision_log() -> InMemoryDecisionLog:
    return InMemoryDecisionLog()


@pytest.fixture
def policy_engine(
    fake_redis, config_dir, decision_log: InMemoryDecisionLog
) -> Iterator[PolicyEngine]:
    """A real PolicyEngine, built from the shipped ``config/sources.yaml``.

    Only ``fixture_replay`` is enabled there, so this can reach the fixture server and
    nothing else — the same restriction a real deployment has today.
    """
    config = load_sources(config_dir)
    engine = PolicyEngine(
        config=config,
        redis_client=fake_redis,
        decision_log=decision_log,
        user_agent="APIx-Test/1.0 (+test@example.org)",
    )
    try:
        yield engine
    finally:
        engine.close()
