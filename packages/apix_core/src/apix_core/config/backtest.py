"""Schema for ``config/backtest.yaml`` — scoring APIx against DGCA reference fares.

The reporting window has a hard floor at 30 days because the problem statement
requires at least that much back-tested history; the actual window used for a given
run — which may be shorter than configured if less history exists — is always reported
alongside the configured value in ``docs/backtest.md`` (see
``docs/generate_backtest_report.py``), never presented as if it were the configured one.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BacktestConfigFile(BaseModel):
    """The whole ``config/backtest.yaml`` file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1, max_length=32)
    description: str = ""

    reporting_window_days: int = Field(ge=30)
    min_periods_for_correlation: int = Field(ge=3)
    # Empty means "every basket route with a matching dgca_fare_reference row".
    routes: list[str] = Field(default_factory=list)


__all__ = ["BacktestConfigFile"]
