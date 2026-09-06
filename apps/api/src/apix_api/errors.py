"""RFC 9457 problem+json error handling.

Every non-2xx response from this service is a problem document with the media type
``application/problem+json``. There is no second error shape.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"

# Problem types are stable URIs. They are part of the contract: a client may switch on
# them, so a value here is never repurposed.
PROBLEM_BASE = "https://apix.example.org/problems"


class Problem(BaseModel):
    """An RFC 9457 problem detail object."""

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "type": f"{PROBLEM_BASE}/series-not-found",
                "title": "Series not found",
                "status": 404,
                "detail": "No series is published with code 'APIX.ALL.M'.",
                "instance": "/v1/index",
                "trace_id": "01JB8Q0000000000000000",
            }
        },
    )

    type: str = Field(description="Stable URI identifying the problem type.")
    title: str = Field(description="Short, human-readable summary. Does not change per occurrence.")
    status: int = Field(ge=400, le=599, description="HTTP status code.")
    detail: str | None = Field(default=None, description="Explanation specific to this occurrence.")
    instance: str | None = Field(default=None, description="URI of the specific occurrence.")
    trace_id: str | None = Field(
        default=None, description="Correlates this response with the server's structured logs."
    )


class ValidationProblem(Problem):
    """A 422 problem, carrying the individual field errors."""

    errors: list[dict[str, Any]] = Field(
        default_factory=list, description="One entry per rejected field."
    )


def problem_response(
    *,
    request: Request,
    status_code: int,
    problem_type: str,
    title: str,
    detail: str | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build a problem+json response."""
    body = Problem(
        type=f"{PROBLEM_BASE}/{problem_type}",
        title=title,
        status=status_code,
        detail=detail,
        instance=str(request.url.path),
        trace_id=request.headers.get("x-request-id"),
    ).model_dump(mode="json")
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status_code, content=body, media_type=PROBLEM_MEDIA_TYPE)


_TITLES = {
    status.HTTP_400_BAD_REQUEST: ("bad-request", "Bad request"),
    status.HTTP_401_UNAUTHORIZED: ("unauthorized", "Unauthorized"),
    status.HTTP_403_FORBIDDEN: ("forbidden", "Forbidden"),
    status.HTTP_404_NOT_FOUND: ("not-found", "Resource not found"),
    status.HTTP_409_CONFLICT: ("conflict", "Conflict"),
    status.HTTP_422_UNPROCESSABLE_CONTENT: ("validation-error", "Request validation failed"),
    status.HTTP_429_TOO_MANY_REQUESTS: ("rate-limited", "Too many requests"),
    status.HTTP_500_INTERNAL_SERVER_ERROR: ("internal-error", "Internal server error"),
    status.HTTP_503_SERVICE_UNAVAILABLE: ("unavailable", "Service unavailable"),
}


def install_error_handlers(app: FastAPI) -> None:
    """Replace FastAPI's default error shapes with problem+json."""

    # Registered against the Starlette base class, not FastAPI's subclass: an
    # unmatched route raises the former, and a handler on the subclass would miss it.
    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        slug, title = _TITLES.get(exc.status_code, ("error", "Error"))
        return problem_response(
            request=request,
            status_code=exc.status_code,
            problem_type=slug,
            title=title,
            detail=str(exc.detail) if exc.detail else None,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return problem_response(
            request=request,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            problem_type="validation-error",
            title="Request validation failed",
            detail="One or more query parameters or path segments are invalid.",
            extra={"errors": [dict(e) for e in exc.errors()]},
        )


# Reusable OpenAPI response declarations so every endpoint documents the same errors.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": Problem, "description": "Bad request", "content": {PROBLEM_MEDIA_TYPE: {}}},
    404: {"model": Problem, "description": "Not found", "content": {PROBLEM_MEDIA_TYPE: {}}},
    422: {
        "model": ValidationProblem,
        "description": "Validation failed",
        "content": {PROBLEM_MEDIA_TYPE: {}},
    },
    429: {"model": Problem, "description": "Rate limited", "content": {PROBLEM_MEDIA_TYPE: {}}},
    500: {"model": Problem, "description": "Internal error", "content": {PROBLEM_MEDIA_TYPE: {}}},
}
