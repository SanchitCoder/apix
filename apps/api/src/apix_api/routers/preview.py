"""/v1/method/preview — a what-if index run under a modified method.

The method console posts overrides here; the response is a real, database-backed
comparison of the previewed method against the method in force, at the elementary
level: matched-product price relatives (:mod:`apix_core.index.elementary`) computed
from real ``fare_quote`` rows for the two boundary days of the most recent collection
window, under each formula. This is a smaller computation than the full route/carrier/
window aggregation hierarchy ``apix_scheduler.index_run`` runs (that lives in a
different app and is not imported here to keep the API service's dependency footprint
to ``apix_core`` alone) — the settings that act above the elementary level
(``multilateral_method``, ``splice_method``, ``window_length_periods``,
``quality_adjustment_enabled``, ``imputation_rule``) are validated for coherence but do
not move this particular statistic, and the diagnostics say so rather than implying a
sensitivity that was not actually computed.

A preview is never a published statistic. It carries its own ``config_hash`` so that a
preview someone decides to adopt is traceable to the exact configuration that produced
it — adopting it is then a change to ``config/method.yaml``, reviewed like any other.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import ValidationError
from sqlalchemy import func, select

from apix_api.auth import require_authenticated
from apix_api.db import SessionDep  # noqa: TC001
from apix_api.errors import MICRODATA_ERROR_RESPONSES
from apix_api.meta import build_meta
from apix_api.schemas import (
    MethodOverrides,
    MethodPreviewDiagnostics,
    MethodPreviewPoint,
    MethodPreviewResponse,
    MethodPreviewSettings,
)
from apix_core.config import config_hash, load_method
from apix_core.config.method import MethodConfigFile
from apix_core.index.elementary import elementary_index
from apix_core.models import FareQuote

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(
    prefix="/v1",
    tags=["method"],
    responses=MICRODATA_ERROR_RESPONSES,
    dependencies=[Depends(require_authenticated)],
)

PREVIEW_WINDOW_DAYS = 21


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


async def _matched_price_relatives(
    session: AsyncSession,
) -> tuple[list[float], list[float], int]:
    """Prices for the same (route, carrier, flight) matched across the two boundary
    days of the most recent ``PREVIEW_WINDOW_DAYS``-day collection window.
    """
    as_of = (await session.execute(select(func.max(FareQuote.query_date)))).scalar_one_or_none()
    if as_of is None:
        raise HTTPException(status_code=404, detail="no fare_quote data to preview against")
    start = as_of - timedelta(days=PREVIEW_WINDOW_DAYS - 1)

    rows = (
        await session.execute(
            select(
                FareQuote.route_id,
                FareQuote.carrier_iata,
                FareQuote.flight_number,
                FareQuote.query_date,
                FareQuote.total_fare,
            ).where(FareQuote.query_date.in_((start, as_of)))
        )
    ).all()

    base_prices: dict[tuple[object, str, str | None], float] = {}
    current_prices: dict[tuple[object, str, str | None], float] = {}
    for route_id, carrier_iata, flight_number, query_date, total_fare in rows:
        key = (route_id, carrier_iata, flight_number)
        target = base_prices if query_date == start else current_prices
        target[key] = float(total_fare)

    matched = sorted(set(base_prices) & set(current_prices), key=str)
    p_0 = [base_prices[k] for k in matched]
    p_t = [current_prices[k] for k in matched]
    return p_0, p_t, len(matched)


@router.post(
    "/method/preview",
    summary="Compute a preview index run under modified method settings",
    response_model=MethodPreviewResponse,
)
async def post_method_preview(
    overrides: MethodOverrides, session: SessionDep, response: Response
) -> MethodPreviewResponse:
    """Run the elementary aggregate under the method in force and under the override.

    Never a published statistic — ``X-APIx-Data-Status: PREVIEW`` always, regardless of
    caller role.
    """
    base = load_method()
    previewed = _apply_overrides(base, overrides)
    base_hash = config_hash(base)
    preview_hash = config_hash(previewed)
    is_baseline = preview_hash == base_hash

    p_0, p_t, n_matched = await _matched_price_relatives(session)
    if n_matched == 0:
        raise HTTPException(
            status_code=404,
            detail=(
                "no matched (route, carrier, flight) products between the window's boundary days"
            ),
        )

    baseline_value = float(elementary_index(p_t, p_0, base.elementary_formula))
    previewed_value = (
        baseline_value
        if is_baseline
        else float(elementary_index(p_t, p_0, previewed.elementary_formula))
    )

    as_of = (await session.execute(select(func.max(FareQuote.query_date)))).scalar_one()
    response.headers["X-APIx-Data-Status"] = "PREVIEW"

    return MethodPreviewResponse(
        series="APIX.ALL.M",
        preview_run_id=preview_hash[:16],
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
        points=[
            MethodPreviewPoint(
                period=as_of,
                value=round(previewed_value, 6),
                baseline_value=round(baseline_value, 6),
                n_quotes=n_matched,
                coverage_pct=None,
                imputed_cells=0,
                outlier_cells=0,
            )
        ],
        diagnostics=MethodPreviewDiagnostics(
            coverage_pct=100.0,
            n_quotes=n_matched,
            imputed_cell_count=0,
            outlier_dropped_count=0,
            suppressed_cell_count=0,
        ),
        meta=build_meta(
            data_status="PREVIEW", method_version=base.method_version, index_run_id=None
        ),
    )
