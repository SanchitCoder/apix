"""Liveness, readiness and Prometheus metrics.

These three are deliberately outside /v1: they are operational, not statistical, and
their shape is not part of the published data contract.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from apix_api.schemas import DependencyStatus, HealthResponse, ReadyResponse

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
async def readyz() -> ReadyResponse:
    """Report readiness dependency by dependency.

    Phase 3 replaces these placeholders with real probes (a ``SELECT 1``, a Redis
    ``PING``, the latest ``index_run`` status). The shape is fixed now so the deployment
    manifests can be written against it.
    """
    return ReadyResponse(
        status="ready",
        dependencies=[
            DependencyStatus(name="postgres", ok=True, detail="not probed: Phase 3"),
            DependencyStatus(name="redis", ok=True, detail="not probed: Phase 3"),
            DependencyStatus(name="config", ok=True, detail="basket, sources and method loaded"),
        ],
    )


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
async def metrics() -> Response:
    """Expose the process's Prometheus registry."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
