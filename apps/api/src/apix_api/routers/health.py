"""Liveness, readiness and Prometheus metrics.

These three are deliberately outside /v1: they are operational, not statistical, and
their shape is not part of the published data contract.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from apix_api.db import SessionDep  # noqa: TC001
from apix_api.metrics import refresh_gauges
from apix_api.schemas import DependencyStatus, HealthResponse, ReadyResponse
from apix_core.config import ConfigError, load_basket, load_method, load_sources

router = APIRouter(tags=["operations"])


@router.get(
    "/healthz",
    summary="Liveness probe",
    response_model=HealthResponse,
    responses={200: {"description": "The process is running."}},
)
async def healthz() -> HealthResponse:
    """Return 200 whenever the process is up.

    Deliberately checks nothing else: a liveness probe that depends on the database
    restarts the API every time Postgres blinks.
    """
    from apix_api import __version__

    return HealthResponse(version=__version__)


@router.get(
    "/readyz",
    summary="Readiness probe",
    response_model=ReadyResponse,
    responses={
        200: {"description": "Per-dependency readiness. 200 even when degraded."},
    },
)
async def readyz(session: SessionDep, request: Request) -> ReadyResponse:
    """Report readiness dependency by dependency: a real ``SELECT 1``, a real Redis
    ``PING``, and the three config files loaded and validated.
    """
    dependencies: list[DependencyStatus] = []

    try:
        await session.execute(text("SELECT 1"))
        dependencies.append(DependencyStatus(name="postgres", ok=True, detail=None))
    except Exception as exc:
        dependencies.append(DependencyStatus(name="postgres", ok=False, detail=str(exc)))

    try:
        pong = await request.app.state.cache_redis.ping()
        dependencies.append(DependencyStatus(name="redis", ok=bool(pong), detail=None))
    except Exception as exc:
        dependencies.append(DependencyStatus(name="redis", ok=False, detail=str(exc)))

    try:
        load_basket()
        load_sources()
        load_method()
        dependencies.append(
            DependencyStatus(name="config", ok=True, detail="basket, sources and method loaded")
        )
    except ConfigError as exc:
        dependencies.append(DependencyStatus(name="config", ok=False, detail=str(exc)))

    status: Literal["ready", "degraded", "not_ready"]
    if all(d.ok for d in dependencies):
        status = "ready"
    elif any(d.ok for d in dependencies):
        status = "degraded"
    else:
        status = "not_ready"
    return ReadyResponse(status=status, dependencies=dependencies)


@router.get(
    "/metrics",
    summary="Prometheus metrics",
    response_class=Response,
    responses={
        200: {
            "description": "Prometheus text exposition format.",
            "content": {CONTENT_TYPE_LATEST: {"schema": {"type": "string"}}},
        }
    },
)
async def metrics(session: SessionDep) -> Response:
    """Expose the process's Prometheus registry, refreshing the DB-derived gauges first."""
    await refresh_gauges(session)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
