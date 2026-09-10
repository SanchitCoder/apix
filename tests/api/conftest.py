"""Fixtures for API tests that need a real, seeded database.

Every test in this package now runs against real fare_quote/index_run rows, not
hard-coded examples — so, unlike the rest of the unit suite, this package needs a real
Postgres (via the session-scoped ``postgres_url`` fixture in ``tests/conftest.py``) and
is marked ``integration``.

The headline series ``APIX.ALL.M`` is honestly unpublishable against the shipped
``config/basket.yaml`` (every route's ``dgca_pax_share`` is null — a documented Phase 2
gap, and ``apix_core.index.aggregate.national_index`` correctly refuses to guess a
weight). Tests that need real, non-empty index data therefore target a route-level
series (``APIX.ROUTE.DEL-BOM.M``), not the headline.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import TYPE_CHECKING

import fakeredis
import pytest
import schemathesis
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apix_core.models import ApiKey, Role
from apix_core.policy.ratelimit import TokenBucketLimiter
from apix_core.provenance.hashing import sha256_hex
from apix_core.settings import get_settings
from apix_core.testing.seed import seed_synthetic
from apix_scheduler.index_run import compute_and_persist
from tests.conftest import requires_docker

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI
    from schemathesis.schemas import BaseSchema

pytestmark = [pytest.mark.integration, requires_docker]

SEED_DAYS = 75
LATEST_SEEDED_DATE = date(2026, 8, 31)
FIRST_AS_OF = date(2026, 8, 10)
SECOND_AS_OF = date(2026, 8, 20)
WINDOW_DAYS = 21
ROUTE_SERIES = "APIX.ROUTE.DEL-BOM.M"
RESEARCHER_API_KEY = "test-researcher-key-do-not-use-in-prod"


def _to_async_url(sync_url: str) -> str:
    return sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")


@pytest.fixture(scope="session")
def seeded_database_url(postgres_url: str, repo_root: Path) -> str:
    """Migrate, seed the synthetic dataset, and publish two real vintages of one
    period — the shared fixture behind every test in this package.
    """
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(config, "head")

    start_query_date = LATEST_SEEDED_DATE - timedelta(days=SEED_DAYS - 1)
    seed_synthetic(postgres_url, SEED_DAYS, start_query_date, repo_root)

    engine = create_engine(postgres_url)
    try:
        with Session(engine) as session:
            compute_and_persist(session, FIRST_AS_OF, WINDOW_DAYS)
            compute_and_persist(session, SECOND_AS_OF, WINDOW_DAYS)

            key_row = ApiKey(
                id=uuid.uuid4(),
                key_hash=sha256_hex(RESEARCHER_API_KEY.encode("utf-8")),
                role=Role.RESEARCHER,
                label="test fixture",
            )
            session.add(key_row)
            session.commit()
    finally:
        engine.dispose()

    return postgres_url


@pytest.fixture(scope="session")
def a_real_quote_id(seeded_database_url: str) -> uuid.UUID:
    """A ``fare_quote.id`` that genuinely fed a published route-series value — the
    provenance chain a test can assert real things about.
    """
    from apix_core.models import FareQuoteClean, IndexValueQuote, Series

    engine = create_engine(seeded_database_url)
    try:
        with Session(engine) as session:
            row = session.execute(
                select(FareQuoteClean.quote_id)
                .join(IndexValueQuote, IndexValueQuote.clean_id == FareQuoteClean.id)
                .join(Series, Series.id == IndexValueQuote.series_id)
                .where(Series.code == ROUTE_SERIES, FareQuoteClean.quote_id.isnot(None))
                .limit(1)
            ).scalar_one()
    finally:
        engine.dispose()
    return row


@asynccontextmanager
async def _running_app(seeded_database_url: str) -> AsyncIterator[FastAPI]:
    """The real application, lifespan-started against the seeded test database, with
    fake (in-process) Redis standing in for cache and rate limits — no compose stack
    required to run this suite.
    """
    from apix_api.main import create_app

    original_env = {
        key: os.environ.get(key)
        for key in ("APIX_DATABASE_URL", "APIX_DATABASE_SYNC_URL", "APIX_ENV")
    }
    os.environ["APIX_DATABASE_URL"] = _to_async_url(seeded_database_url)
    os.environ["APIX_DATABASE_SYNC_URL"] = seeded_database_url
    os.environ["APIX_ENV"] = "ci"
    get_settings.cache_clear()

    app: FastAPI = create_app()
    try:
        async with app.router.lifespan_context(app):
            app.state.cache_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
            sync_fake_redis = fakeredis.FakeStrictRedis(decode_responses=False)
            app.state.rate_limiter = TokenBucketLimiter(sync_fake_redis)
            yield app
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


@pytest.fixture
async def api_async_client(seeded_database_url: str) -> AsyncIterator[AsyncClient]:
    """An httpx client over the running, seeded application."""
    async with _running_app(seeded_database_url) as app:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://apix.test") as client:
            yield client


@pytest.fixture
async def api_schema(seeded_database_url: str) -> AsyncIterator[BaseSchema]:
    """The OpenAPI schema, loaded from the running, seeded application — what
    ``tests/api/test_schema_contract.py`` fuzzes against.
    """
    async with _running_app(seeded_database_url) as app:
        yield schemathesis.openapi.from_asgi("/openapi.json", app)


@pytest.fixture
def researcher_headers() -> dict[str, str]:
    return {"X-API-Key": RESEARCHER_API_KEY}
