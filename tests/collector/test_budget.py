from __future__ import annotations

import pytest

from apix_collector.budget import RunBudget
from apix_collector.errors import BudgetExceeded


def test_reserve_within_budget_succeeds() -> None:
    budget = RunBudget("test_source", 3)
    budget.reserve()
    budget.reserve()
    assert budget.spent == 2
    assert budget.remaining == 1


def test_reserve_beyond_budget_raises_and_does_not_spend() -> None:
    budget = RunBudget("test_source", 1)
    budget.reserve()
    with pytest.raises(BudgetExceeded) as excinfo:
        budget.reserve()
    assert excinfo.value.source_code == "test_source"
    assert excinfo.value.limit == 1
    assert budget.spent == 1  # the failed reservation never counted


def test_max_requests_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_requests"):
        RunBudget("test_source", 0)
