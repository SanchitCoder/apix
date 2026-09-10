"""Structured, JSON logging for the API process. Called once, from ``create_app()``.

Every log line carries ``request_id`` (bound by ``middleware.install_request_middleware``)
so a line in the log stream can be tied back to the response that produced it, and from
there to ``Problem.trace_id`` on any error the same request raised.
"""

from __future__ import annotations

import logging

import structlog


def configure_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    logging.basicConfig(level=level, format="%(message)s")

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


__all__ = ["configure_logging"]
