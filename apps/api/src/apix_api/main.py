"""APIx public API.

Phase 1 scaffolding: every endpoint returns a correctly-typed example payload so the
front end and any SDMX consumer can be built against a frozen contract. There is no
database access in this phase, by design.

Every /v1 response carries ``X-APIx-Data-Status: EXAMPLE_ONLY`` and a ``meta`` block
saying the same thing, so a placeholder can never be mistaken for a published statistic.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from apix_api import __version__
from apix_api.errors import install_error_handlers
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
from apix_core.config import ConfigError, load_basket, load_method, load_sources
from apix_core.settings import get_settings

DATA_STATUS_HEADER = "X-APIx-Data-Status"
DATA_STATUS = "EXAMPLE_ONLY"

DESCRIPTION = """
Real-time airfare price index for India.

**This deployment serves example data.** Every `/v1` response is a hard-coded
placeholder carrying `meta.data_status = "EXAMPLE_ONLY"` and the header
`X-APIx-Data-Status: EXAMPLE_ONLY`. The purpose of this phase is to freeze the contract,
not to publish numbers. The two exceptions are `/v1/metadata/basket` and
`/v1/metadata/method`, which serve the real, validated contents of `config/`.

**Errors** are RFC 9457 problem documents (`application/problem+json`).

**Pagination** is cursor-based. List responses carry `pagination.next_cursor`; pass it
back unchanged as `cursor`. Cursors are bound to the filter parameters that produced
them — reusing one against different filters is rejected rather than silently wrong.

**Provenance**: `/v1/provenance/{quote_id}` resolves any observation back to its source,
timestamp and legal basis.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001 — FastAPI's signature
    """Validate configuration at startup.

    All three config files are loaded and validated before the service accepts traffic.
    An invalid basket or method is a startup failure, not a 500 discovered later by a
    consumer.
    """
    try:
        load_basket()
        load_sources()
        load_method()
    except ConfigError as exc:  # pragma: no cover - exercised by config tests
        raise RuntimeError(f"APIx cannot start: invalid configuration.\n{exc}") from exc
    yield


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
        """Mark every statistical response as a placeholder.

        Removed in Phase 3, when the header starts reporting the real status of the
        underlying index run instead.
        """
        response = await call_next(request)
        if request.url.path.startswith("/v1"):
            response.headers.setdefault(DATA_STATUS_HEADER, DATA_STATUS)
        return response

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
