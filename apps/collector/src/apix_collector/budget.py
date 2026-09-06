"""Per-run request budgets.

A spider is handed one ``RunBudget`` per invocation of ``collect()``. Every acquisition
attempt — including retries — reserves against it first, so a retry storm against one
route can never turn into an unbounded number of requests to a source.
"""

from __future__ import annotations

from apix_collector.errors import BudgetExceeded


class RunBudget:
    """A consumable request allowance, scoped to one spider run."""

    def __init__(self, source_code: str, max_requests: int) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        self._source_code = source_code
        self._max = max_requests
        self._spent = 0

    @property
    def spent(self) -> int:
        return self._spent

    @property
    def remaining(self) -> int:
        return self._max - self._spent

    def reserve(self, n: int = 1) -> None:
        """Reserve ``n`` requests against the budget, or raise :class:`BudgetExceeded`.

        Raised *before* the request is made — the budget never goes negative and a
        denied reservation never counts as spent.
        """
        if self._spent + n > self._max:
            raise BudgetExceeded(self._source_code, self._max)
        self._spent += n


__all__ = ["RunBudget"]
