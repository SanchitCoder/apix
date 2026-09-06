"""/v1/method/preview — a what-if index run under a modified method.

The method console posts overrides here; the response is the series as the modified
method would compute it, next to the series under the method in force, with the
diagnostics (coverage, imputation, outliers) a statistician weighs a method change by.

A preview is never a published statistic. It carries its own ``config_hash`` so that a
preview someone decides to adopt is traceable to the exact configuration that produced
it — adopting it is then a change to ``config/method.yaml``, reviewed like any other.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError

from apix_api.errors import ERROR_RESPONSES
from apix_api.examples import (
    EXAMPLE_PERIODS,
    EXAMPLE_PREVIEW_RUN_ID,
    EXAMPLE_SERIES_CODE,
    EXAMPLE_VALUES,
    example_offset,
    response_meta,
)
from apix_api.schemas import (
    MethodOverrides,
    MethodPreviewDiagnostics,
    MethodPreviewPoint,
    MethodPreviewResponse,
    MethodPreviewSettings,
)
from apix_core.config import config_hash, load_method
from apix_core.config.method import MethodConfigFile

router = APIRouter(prefix="/v1", tags=["method"], responses=ERROR_RESPONSES)


def _apply_overrides(base: MethodConfigFile, overrides: MethodOverrides) -> MethodConfigFile:
    """Merge overrides into the method in force and re-validate the result.

    Validation runs through ``MethodConfigFile`` itself, so a preview cannot request a
    configuration the system would refuse to publish (a Carli elementary aggregate, an
    out-of-range window). The rejection is the same 422 problem document any other bad
    request gets.
    """
    merged: dict[str, Any] = base.model_dump(mode="json")
    if overrides.elementary_formula is not None:
        merged["elementary_formula"] = overrides.elementary_formula.value
    if overrides.multilateral_method is not None:
        merged["multilateral_method"] = overrides.multilateral_method.value
    if overrides.window_length_periods is not None:
        merged["window"]["length_periods"] = overrides.window_length_periods
    if overrides.splice_method is not None:
        merged["splice_method"] = overrides.splice_method.value
    if overrides.quality_adjustment_enabled is not None:
        merged["quality_adjustment"]["enabled"] = overrides.quality_adjustment_enabled
    if overrides.imputation_rule is not None:
        merged["imputation_rule"] = overrides.imputation_rule.value
    try:
        return MethodConfigFile.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="; ".join(e["msg"] for e in exc.errors()),
        ) from exc


@router.post(
    "/method/preview",
    summary="Compute a preview index run under modified method settings",
    response_model=MethodPreviewResponse,
)
async def post_method_preview(overrides: MethodOverrides) -> MethodPreviewResponse:
    """Run the index under the method in force with the given fields changed.

    In this phase the preview values are placeholders, like every other number this
    service serves — but they are a deterministic function of the previewed
    configuration's hash, so the same settings always preview to the same series and
    any change to a setting visibly moves the line. Phase 3 replaces the arithmetic
    with a real run against the current snapshot; the response shape is the contract.
    """
    base = load_method()
    previewed = _apply_overrides(base, overrides)
    base_hash = config_hash(base)
    preview_hash = config_hash(previewed)
    is_baseline = preview_hash == base_hash

    shift = 0.0 if is_baseline else example_offset("preview", preview_hash, scale=4.0)
    imputed = 0 if previewed.imputation_rule.value == "none" else 12
    outliers = 8 * len(previewed.outlier_rules)
    points = [
        MethodPreviewPoint(
            period=period,
            value=round(
                value + shift + example_offset("preview-period", preview_hash, str(period)), 1
            )
            if not is_baseline
            else value,
            baseline_value=value,
            n_quotes=12_500,
            coverage_pct=96.0,
            imputed_cells=imputed // len(EXAMPLE_PERIODS) + 1 if imputed else 0,
            outlier_cells=outliers // len(EXAMPLE_PERIODS) + 1 if outliers else 0,
        )
        for period, value in zip(EXAMPLE_PERIODS, EXAMPLE_VALUES, strict=True)
    ]
    return MethodPreviewResponse(
        series=EXAMPLE_SERIES_CODE,
        preview_run_id=EXAMPLE_PREVIEW_RUN_ID,
        is_baseline=is_baseline,
        settings=MethodPreviewSettings(
            elementary_formula=previewed.elementary_formula,
            multilateral_method=previewed.multilateral_method,
            window_length_periods=previewed.window.length_periods,
            splice_method=previewed.splice_method,
            quality_adjustment_enabled=previewed.quality_adjustment.enabled,
            imputation_rule=previewed.imputation_rule,
        ),
        config_hash=preview_hash,
        baseline_config_hash=base_hash,
        points=points,
        diagnostics=MethodPreviewDiagnostics(
            coverage_pct=96.0,
            n_quotes=12_500,
            imputed_cell_count=imputed,
            outlier_dropped_count=outliers,
            suppressed_cell_count=2,
        ),
        meta=response_meta(method_version=base.method_version, basket_version="2026.1"),
    )
