"""Exceptions raised inside the collector.

None of these are bugs by default — a denied route, a drifted schema and an exhausted
retry budget are all expected outcomes of crawling real websites. Each one carries
enough structure that ``apix_collector.run`` can turn it into a ``collection_run`` row
without inspecting a message string.
"""

from __future__ import annotations


class CollectorError(RuntimeError):
    """Base class for everything raised inside apix_collector."""


class FetchFailed(CollectorError):  # noqa: N818 — the name is the API contract
    """One acquisition attempt came back with a non-success status.

    Not raised for a policy denial or a CAPTCHA — those have their own exceptions
    upstream in ``apix_core.policy`` and are never retried. This is for the ordinary
    HTTP-level failure (a 500, a malformed JSON body) that a strategy decides is worth
    a retry or a fallback to the next strategy.
    """

    def __init__(self, status_code: int, url: str, *, detail: str | None = None) -> None:
        self.status_code = status_code
        self.url = url
        message = f"fetch failed: HTTP {status_code} for {url}"
        if detail:
            message += f" ({detail})"
        super().__init__(message)


class BudgetExceeded(CollectorError):  # noqa: N818 — the name is the API contract
    """A spider tried to spend more requests than its per-run budget allows.

    The budget exists so one misbehaving route (an infinite retry loop, a strategy
    that never gives up) cannot turn into an unbounded hammering of a source. Raised
    before the request is made — the budget is never allowed to go negative.
    """

    def __init__(self, source_code: str, limit: int) -> None:
        self.source_code = source_code
        self.limit = limit
        super().__init__(f"{source_code}: per-run request budget of {limit} exhausted")


class AllStrategiesFailed(CollectorError):  # noqa: N818 — the name is the API contract
    """Every acquisition strategy a spider declared failed for this request.

    Carries the per-strategy failure reasons so the ``collection_run.error_detail``
    written by the caller shows exactly what was tried, not just that nothing worked.
    """

    def __init__(self, source_code: str, route_code: str, attempts: list[str]) -> None:
        self.source_code = source_code
        self.route_code = route_code
        self.attempts = attempts
        super().__init__(
            f"{source_code}/{route_code}: all strategies failed: {'; '.join(attempts)}"
        )


class SchemaDriftError(CollectorError):
    """A mapper could not recognise the shape of a source's response.

    Raised by a mapper, never repaired automatically (CLAUDE.md/task guardrail): the
    only response is to capture the offending payload and make the failure loud. See
    ``apix_collector.drift``.
    """

    def __init__(self, source_code: str, reason: str) -> None:
        self.source_code = source_code
        self.reason = reason
        super().__init__(f"{source_code}: schema drift — {reason}")


__all__ = [
    "AllStrategiesFailed",
    "BudgetExceeded",
    "CollectorError",
    "FetchFailed",
    "SchemaDriftError",
]
