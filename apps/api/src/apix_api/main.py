"""APIx public API.

Every ``/v1`` endpoint is backed by the database: published series are public, draft/
pre-release figures and microdata (quotes, exports, provenance, method preview) require
a researcher or official API key. Responses that are not yet a published statistic say
so via ``X-APIx-Data-Status`` and ``meta.data_status`` — a placeholder or a draft number
must never be mistakable for a published one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import redis.asyncio as redis_asyncio
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis as SyncRedis

from apix_api import __version__
from apix_api.db import (
    create_engine,
    create_session_factory,
    create_sync_provenance_engine,
    create_sync_session_factory,
)
from apix_api.errors import install_error_handlers
from apix_api.logging import configure_logging
from apix_api.metrics import install_metrics_middleware
from apix_api.middleware import install_request_middleware
from apix_api.routers import (
    analytics,
    export,
    health,
    index,
    metadata,
    preview,
    provenance,
    quotes,
    routes,
    sdmx,
)
from apix_core.config import ConfigError, load_access, load_basket, load_method, load_sources
from apix_core.models import Role
from apix_core.policy.ratelimit import TokenBucketLimiter
from apix_core.settings import get_settings

DATA_STATUS_HEADER = "X-APIx-Data-Status"
DEFAULT_DATA_STATUS = "PUBLISHED"

DESCRIPTION = """
Real-time airfare price index for India.

Published index series and route-level metadata are open to the public. Draft/
pre-release figures and microdata (individual quotes, provenance, CSV exports, method
preview) require a researcher or official API key (`X-API-Key`).

**Data status**: every `/v1` response carries `X-APIx-Data-Status` and `meta.data_status`
(`PUBLISHED`, `PROVISIONAL` for a draft run a keyed caller asked for, or `PREVIEW` for a
what-if method run, which is never a published statistic).

**Errors** are RFC 9457 problem documents (`application/problem+json`).

**Pagination** is cursor-based. List responses carry `pagination.next_cursor`; pass it
back unchanged as `cursor`. Cursors are bound to the filter parameters that produced
them — reusing one against different filters is rejected rather than silently wrong.

**Provenance**: `/v1/provenance/{quote_id}` resolves any observation back to its source,
timestamp and legal basis.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate configuration, then bring up the database engine and Redis clients.

    An invalid config file or an unreachable database is a startup failure, not a 500
    discovered later by a consumer.
    """
    settings = get_settings()
    try:
        load_basket()
        load_sources()
        load_method()
        access = load_access()
    except ConfigError as exc:  # pragma: no cover - exercised by config tests
        raise RuntimeError(f"APIx cannot start: invalid configuration.\n{exc}") from exc

    configure_logging(level=settings.log_level, json_output=settings.log_format == "json")

    engine = create_engine(settings)
    app.state.db_engine = engine
    app.state.db_session_factory = create_session_factory(engine)

    sync_engine = create_sync_provenance_engine(settings)
    app.state.sync_engine = sync_engine
    app.state.sync_session_factory = create_sync_session_factory(sync_engine)

    app.state.cache_redis = redis_asyncio.from_url(
        settings.redis_url, db=settings.redis_cache_db, decode_responses=False
    )
    rate_limit_redis = SyncRedis.from_url(
        settings.redis_url, db=settings.redis_rate_limit_db, decode_responses=False
    )
    app.state.rate_limiter = TokenBucketLimiter(rate_limit_redis)
    app.state.access_limits = {
        Role.PUBLIC: access.public,
        Role.RESEARCHER: access.researcher,
        Role.OFFICIAL: access.official,
    }

    try:
        yield
    finally:
        await app.state.cache_redis.aclose()
        rate_limit_redis.close()
        sync_engine.dispose()
        await engine.dispose()


def create_app() -> FastAPI:
    """Build the application."""
    settings = get_settings()

    app = FastAPI(
        title="APIx — Airfare Price Index for India",
        version=__version__,
        description=DESCRIPTION,
        openapi_version="3.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "APIx", "url": "https://example.org/apix"},
        license_info={"name": "Open Government Data Licence — India"},
        openapi_tags=[
            {"name": "operations", "description": "Liveness, readiness and metrics."},
            {"name": "index", "description": "Published index series and their vintages."},
            {"name": "routes", "description": "The route basket and per-route fare series."},
            {"name": "analytics", "description": "Lead-time, heatmap, decomposition, coverage."},
            {"name": "metadata", "description": "The basket and the method actually in force."},
            {"name": "method", "description": "What-if preview runs under a modified method."},
            {"name": "provenance", "description": "Audit trail from a number back to a quote."},
            {"name": "sdmx", "description": "SDMX-JSON 2.0 for statistical consumers."},
            {"name": "export", "description": "Flat CSV downloads."},
        ],
    )

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
            expose_headers=[DATA_STATUS_HEADER],
        )

    install_error_handlers(app)

    @app.middleware("http")
    async def _stamp_data_status(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Default every ``/v1`` response to ``PUBLISHED``.

        An endpoint that knows better (a draft run served to a keyed caller, or
        ``/v1/method/preview``, which is never a published statistic) sets the header
        itself before returning; this only fills in the common case.
        """
        response = await call_next(request)
        if request.url.path.startswith("/v1"):
            response.headers.setdefault(DATA_STATUS_HEADER, DEFAULT_DATA_STATUS)
        return response

    install_metrics_middleware(app)
    install_request_middleware(app)

    app.include_router(health.router)
    app.include_router(index.router)
    app.include_router(routes.router)
    app.include_router(analytics.router)
    app.include_router(metadata.router)
    app.include_router(provenance.router)
    app.include_router(quotes.router)
    app.include_router(preview.router)
    app.include_router(sdmx.router)
    app.include_router(export.router)

    return app


app = create_app()
