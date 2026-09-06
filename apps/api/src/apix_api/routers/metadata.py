"""/v1/metadata — the basket and the method, as served to consumers.

These two endpoints are the only ones that read real data in this phase: they serve the
validated contents of ``config/basket.yaml`` and ``config/method.yaml``. That is
deliberate — the basket and the method are published facts about how the index is built,
and they exist today.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter

from apix_api.errors import ERROR_RESPONSES
from apix_api.examples import response_meta
from apix_api.schemas import (
    AdvanceWindowOut,
    BasketMetadata,
    CarrierOut,
    CarriersMetadata,
    MethodMetadata,
    RouteSummary,
)
from apix_core.config import config_hash, load_basket, load_method

router = APIRouter(prefix="/v1/metadata", tags=["metadata"], responses=ERROR_RESPONSES)


@router.get("/basket", summary="The route basket and its weights", response_model=BasketMetadata)
async def get_basket() -> BasketMetadata:
    """Serve the current basket.

    ``weights_populated`` is false and every ``dgca_pax_share`` is null until Phase 2
    loads the DGCA release. A consumer can therefore tell, from the response alone, that
    the index is not yet weighted — rather than discovering it from a footnote.
    """
    basket = load_basket()
    return BasketMetadata(
        basket_version=basket.basket_version,
        effective_from=basket.effective_from,
        description=basket.description,
        n_routes=len(basket.routes),
        weights_populated=basket.weights_are_populated,
        advance_windows=[
            AdvanceWindowOut(code=w.code, min_days=w.min_days, max_days=w.max_days, label=w.label)
            for w in basket.advance_windows
        ],
        routes=[
            RouteSummary(
                code=r.code,
                origin_iata=r.origin,
                origin_city="",
                dest_iata=r.dest,
                dest_city="",
                dgca_pax_share=float(r.dgca_pax_share) if r.dgca_pax_share is not None else None,
                basket_version=basket.basket_version,
                active_from=r.active_from,
                active_to=r.active_to,
            )
            for r in basket.routes
        ],
    )


@router.get("/carriers", summary="Scheduled domestic carriers", response_model=CarriersMetadata)
async def get_carriers() -> CarriersMetadata:
    """Serve the carrier reference list.

    Values mirror ``db/seeds/carriers.csv`` (DGCA scheduled domestic operators) — real
    reference data, not placeholders. Phase 3 serves this from the ``carrier`` table
    the seed loads; the hard-coded copy exists only because this phase has no database.
    """
    rows: list[tuple[str, str, str, Literal["FSC", "LCC", "REGIONAL"]]] = [
        ("AI", "AIC", "Air India", "FSC"),
        ("6E", "IGO", "IndiGo", "LCC"),
        ("IX", "AXB", "Air India Express", "LCC"),
        ("SG", "SEJ", "SpiceJet", "LCC"),
        ("QP", "AKJ", "Akasa Air", "LCC"),
        ("9I", "LLR", "Alliance Air", "REGIONAL"),
    ]
    return CarriersMetadata(
        carriers=[
            CarrierOut(iata=iata, icao=icao, name=name, carrier_type=carrier_type)
            for iata, icao, name, carrier_type in rows
        ],
        meta=response_meta(basket_version="2026.1", with_run=False),
    )


@router.get("/method", summary="The index method in force", response_model=MethodMetadata)
async def get_method() -> MethodMetadata:
    """Serve the validated method configuration and its hash.

    ``config_hash`` is the same value stamped onto every ``index_run``, so a consumer can
    verify that a published number was produced by the method described here.
    """
    method = load_method()
    return MethodMetadata(
        method_version=method.method_version,
        config_hash=config_hash(method),
        description=method.description,
        price_reference_period=method.price_reference_period,
        index_reference_value=method.index_reference_value,
        elementary_formula=method.elementary_formula.value,
        multilateral_method=method.multilateral_method.value,
        window_length_periods=method.window.length_periods,
        window_frequency=method.window.frequency,
        splice_method=method.splice_method.value,
        quality_adjustment_enabled=method.quality_adjustment.enabled,
        quality_adjustment_columns=list(method.quality_adjustment.columns),
        imputation_rule=method.imputation_rule.value,
        outlier_rules=[r.model_dump(mode="json") for r in method.outlier_rules],
        min_quotes_per_cell=method.min_quotes_per_cell,
        min_coverage_pct=method.min_coverage_pct,
    )
