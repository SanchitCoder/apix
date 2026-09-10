"""Data-quality gates, run in CI and before every index run.

Five checks against the cleaned output, backed by Great Expectations so the checks
themselves — not just their results — are auditable:

1. ``base_fare`` is within a plausible range for its route's distance band.
2. ``taxes`` is a plausible share of ``total_fare``.
3. Coverage per ``(route_id, advance_days)`` is above the configured floor.
4. No duplicate ``quote_id`` in the clean table.
5. No row has ``is_imputed = True`` with ``imputation_method`` null.

A failing gate blocks the index run: :func:`run_quality_gates` raises
:class:`QualityGateError` carrying the full report (every gate's result, not just the
first failure) rather than warning and continuing — CLAUDE.md principle 2, nothing fails
silently.

Great Expectations runs here in its fully in-memory "ephemeral" mode: no project
directory, no filesystem writes, no network calls. Its analytics telemetry is disabled
at import time so this stays true offline and in tests, matching the guardrail that
nothing in this codebase makes an outbound request outside the PolicyEngine.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

os.environ.setdefault("GX_ANALYTICS_ENABLED", "false")

import great_expectations as gx
import pandas as pd
from great_expectations.expectations.core.expect_column_values_to_be_between import (
    ExpectColumnValuesToBeBetween,
)
from great_expectations.expectations.core.expect_column_values_to_be_in_set import (
    ExpectColumnValuesToBeInSet,
)
from great_expectations.expectations.core.expect_column_values_to_be_unique import (
    ExpectColumnValuesToBeUnique,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from great_expectations.data_context.data_context.abstract_data_context import (
        AbstractDataContext,
    )
    from great_expectations.expectations.expectation import Expectation

    from apix_core.config.cleaning import QualityGateConfig


@dataclass(frozen=True)
class GateResult:
    """The outcome of one expectation."""

    name: str
    success: bool
    detail: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GateReport:
    """Every gate's result from one :func:`run_quality_gates` call."""

    results: list[GateResult]

    @property
    def success(self) -> bool:
        return all(r.success for r in self.results)

    @property
    def failures(self) -> list[GateResult]:
        return [r for r in self.results if not r.success]


class QualityGateError(RuntimeError):
    """One or more data-quality gates failed. Blocks the index run."""

    def __init__(self, report: GateReport) -> None:
        self.report = report
        names = ", ".join(r.name for r in report.failures)
        super().__init__(f"data quality gates failed: {names}")


def run_quality_gates(
    clean_quotes: pd.DataFrame,
    coverage: pd.DataFrame,
    config: QualityGateConfig,
    route_distance_km: Mapping[str, float],
) -> GateReport:
    """Run all five gates. Returns the report on success, raises on any failure.

    ``clean_quotes`` is the ``fare_quote_clean``-shaped output of the pipeline (imputed
    rows included): it must carry ``route_id``, ``base_fare``, ``taxes``, ``total_fare``,
    ``quote_id``, ``is_outlier``, ``is_imputed`` and ``imputation_method``. ``coverage``
    is the output of :func:`apix_core.clean.missing.compute_coverage`.
    ``route_distance_km`` maps every ``route_id`` present in ``clean_quotes`` to its
    great-circle distance.

    The two per-row plausibility gates (base_fare-per-band and tax-share) are checked
    only against rows *not* already flagged ``is_outlier`` — stage 3 has already caught
    and labelled those individually, and the index layer is expected to exclude them.
    Re-flagging an already-flagged row here would make these gates fail on every
    correctly functioning pipeline run that contains a real, correctly-handled outlier.
    These gates exist to catch a systemic problem (a whole band, currency or route
    priced implausibly) that per-cell outlier screening would not.
    """
    context = gx.get_context(mode="ephemeral")
    plausibility_rows = clean_quotes.loc[~clean_quotes["is_outlier"]]
    results = [
        *_base_fare_within_distance_bands(context, plausibility_rows, config, route_distance_km),
        _tax_share_within_band(context, plausibility_rows, config),
        _coverage_above_floor(context, coverage, config),
        _no_duplicate_quote_id(context, clean_quotes),
        _no_imputed_row_without_method(context, clean_quotes),
    ]
    report = GateReport(results=results)
    if not report.success:
        raise QualityGateError(report)
    return report


def _validate(
    context: AbstractDataContext, df: pd.DataFrame, asset_name: str, expectation: Expectation
) -> GateResult:
    source = context.data_sources.add_pandas(f"src_{asset_name}")
    asset = source.add_dataframe_asset(name=asset_name)
    batch_def = asset.add_batch_definition_whole_dataframe(f"bd_{asset_name}")
    batch = batch_def.get_batch(batch_parameters={"dataframe": df})
    result = batch.validate(expectation)
    success = bool(result.success)
    detail: dict[str, object] = {
        "element_count": result.result.get("element_count"),
        "unexpected_count": result.result.get("unexpected_count"),
        "partial_unexpected_list": result.result.get("partial_unexpected_list"),
    }
    return GateResult(name=asset_name, success=success, detail=detail)


def _base_fare_within_distance_bands(
    context: AbstractDataContext,
    clean_quotes: pd.DataFrame,
    config: QualityGateConfig,
    route_distance_km: Mapping[str, float],
) -> list[GateResult]:
    distance = clean_quotes["route_id"].map(route_distance_km)
    unknown = clean_quotes.loc[distance.isna(), "route_id"].unique()
    if len(unknown) > 0:
        raise ValueError(
            f"run_quality_gates: route_distance_km is missing routes: {sorted(unknown)}"
        )
    band_name = distance.astype(float).map(lambda km: config.band_for_distance(km).name)

    results = []
    for band in config.distance_bands:
        subset = pd.DataFrame({"base_fare": clean_quotes.loc[band_name == band.name, "base_fare"]})
        expectation = ExpectColumnValuesToBeBetween(
            column="base_fare",
            min_value=band.base_fare_min_inr,
            max_value=band.base_fare_max_inr,
        )
        name = f"base_fare_within_band__{band.name}"
        results.append(_validate(context, subset, name, expectation))
    return results


def _tax_share_within_band(
    context: AbstractDataContext, clean_quotes: pd.DataFrame, config: QualityGateConfig
) -> GateResult:
    has_taxes = (
        clean_quotes["taxes"].notna()
        & clean_quotes["total_fare"].notna()
        & clean_quotes["total_fare"].astype(float).ne(0)
    )
    taxes = clean_quotes.loc[has_taxes, "taxes"].astype(float)
    total_fare = clean_quotes.loc[has_taxes, "total_fare"].astype(float)
    df = pd.DataFrame({"tax_share": taxes / total_fare})
    expectation = ExpectColumnValuesToBeBetween(
        column="tax_share", min_value=config.tax_share_min, max_value=config.tax_share_max
    )
    return _validate(context, df, "tax_share_within_band", expectation)


def _coverage_above_floor(
    context: AbstractDataContext, coverage: pd.DataFrame, config: QualityGateConfig
) -> GateResult:
    df = pd.DataFrame({"coverage_pct": coverage["coverage_pct"]})
    expectation = ExpectColumnValuesToBeBetween(
        column="coverage_pct", min_value=config.coverage_floor_pct, max_value=100.0
    )
    return _validate(context, df, "coverage_above_floor", expectation)


def _no_duplicate_quote_id(context: AbstractDataContext, clean_quotes: pd.DataFrame) -> GateResult:
    df = pd.DataFrame({"quote_id": clean_quotes["quote_id"]})
    expectation = ExpectColumnValuesToBeUnique(column="quote_id")
    return _validate(context, df, "no_duplicate_quote_id", expectation)


def _no_imputed_row_without_method(
    context: AbstractDataContext, clean_quotes: pd.DataFrame
) -> GateResult:
    imputed_without_method = clean_quotes["is_imputed"] & clean_quotes["imputation_method"].isna()
    df = pd.DataFrame({"imputed_without_method": imputed_without_method})
    expectation = ExpectColumnValuesToBeInSet(column="imputed_without_method", value_set=[False])
    return _validate(context, df, "no_imputed_row_without_method", expectation)


__all__ = ["GateReport", "GateResult", "QualityGateError", "run_quality_gates"]
