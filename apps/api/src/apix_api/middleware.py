"""Request-scoped middleware: correlation ids, structured logging, and the
auth/rate-limit choke point every ``/v1`` request passes through before routing.

Auth and rate limiting are enforced here, once, rather than per-router — the same
single-choke-point shape ``PolicyEngine`` enforces on the collection side (CLAUDE.md
principle 3, mirrored for inbound traffic).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import anyio
import structlog

from apix_api.auth import API_KEY_HEADER, InvalidApiKeyError, resolve_role
from apix_api.errors import problem_response

if TYPE_CHECKING:
    from fastapi import FastAPI, Request, Response

    from apix_core.config.access import RoleLimit
    from apix_core.models import Role
    from apix_core.policy.ratelimit import TokenBucketLimiter

log = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-Id"


def install_request_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def _correlation_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Generate/propagate a correlation id and bind it to the log context."""
        request_id = request.headers.get(REQUEST_ID_HEADER.lower()) or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers.setdefault(REQUEST_ID_HEADER, request_id)
        return response

    @app.middleware("http")
    async def _enforce_access_control(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # A CORS preflight carries no API key and is not an API call — it must reach
        # CORSMiddleware (registered inside this middleware in the stack) unmetered, or
        # a shared PUBLIC rate-limit bucket exhausted by preflights alone would make
        # every real request from a keyed browser client look CORS-blocked.
        if not request.url.path.startswith("/v1") or request.method == "OPTIONS":
            return await call_next(request)

        session_factory = request.app.state.db_session_factory
        async with session_factory() as session:
            try:
                role, identity = await resolve_role(session, request.headers.get(API_KEY_HEADER))
            except InvalidApiKeyError:
                return problem_response(
                    request=request,
                    status_code=401,
                    problem_type="unauthorized",
                    title="Unauthorized",
                    detail=f"invalid or revoked {API_KEY_HEADER}",
                )

        limits: dict[Role, RoleLimit] = request.app.state.access_limits
        limiter: TokenBucketLimiter = request.app.state.rate_limiter
        role_limit = limits[role]
        verdict = await anyio.to_thread.run_sync(
            lambda: limiter.take(
                f"{role.value}:{identity}",
                crawl_delay_s=0.0,
                max_requests_per_hour=role_limit.requests_per_minute * 60,
                burst=role_limit.burst,
            )
        )
        if not verdict.granted:
            response = problem_response(
                request=request,
                status_code=429,
                problem_type="rate-limited",
                title="Too many requests",
                detail=f"rate limit exceeded for role={role.value} ({verdict.rule})",
            )
            response.headers["Retry-After"] = str(max(1, int(verdict.retry_after_s)))
            return response

        request.state.role = role
        return await call_next(request)


__all__ = ["REQUEST_ID_HEADER", "install_request_middleware"]
