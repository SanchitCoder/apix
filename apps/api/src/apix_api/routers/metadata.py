"""/v1/metadata — the basket, the carrier reference and the method, as served to
consumers.
"""

from __future__ import annotations

from typing import Literal, cast

from fastapi import APIRouter
from sqlalchemy import select

from apix_api.db import SessionDep  # noqa: TC001
from apix_api.errors import ERROR_RESPONSES
from apix_api.meta import build_meta
from apix_api.schemas import (
    AdvanceWindowOut,
    BasketMetadata,
    CarrierOut,
    CarriersMetadata,
    MethodMetadata,
    RouteSummary,
)
from apix_core.config import config_hash, load_basket, load_method
from apix_core.models import Airport, Carrier

router = APIRouter(prefix="/v1/metadata", tags=["metadata"], responses=ERROR_RESPONSES)


@router.get("/basket", summary="The route basket and its weights", response_model=BasketMetadata)
async def get_basket(session: SessionDep) -> BasketMetadata:
    """Serve the current basket.

    ``weights_populated`` is false and every ``dgca_pax_share`` is null until the DGCA
    release is loaded into ``config/basket.yaml``. A consumer can therefore tell, from
    the response alone, that the index is not yet weighted — rather than discovering it
    from a footnote.
    """
    basket = load_basket()
    city_by_iata: dict[str, str] = dict(
        (await session.execute(select(Airport.iata, Airport.city))).tuples().all()
    )
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
                origin_city=city_by_iata.get(r.origin, ""),
                dest_iata=r.dest,
                dest_city=city_by_iata.get(r.dest, ""),
                dgca_pax_share=float(r.dgca_pax_share) if r.dgca_pax_share is not None else None,
                basket_version=basket.basket_version,
                active_from=r.active_from,
                active_to=r.active_to,
            )
            for r in basket.routes
        ],
    )


@router.get("/carriers", summary="Scheduled domestic carriers", response_model=CarriersMetadata)
async def get_carriers(session: SessionDep) -> CarriersMetadata:
    """Serve the carrier reference list from the ``carrier`` table (``db/seeds/carriers.csv``,
    DGCA scheduled domestic operators — real reference data, loaded by ``make seed``).
    """
    rows = (await session.execute(select(Carrier).order_by(Carrier.iata))).scalars().all()
    return CarriersMetadata(
        carriers=[
            CarrierOut(
                iata=row.iata,
                icao=row.icao or "",
                name=row.name,
                carrier_type=cast("Literal['FSC', 'LCC', 'REGIONAL']", row.carrier_type.value),
            )
            for row in rows
            if row.carrier_type.value in ("FSC", "LCC", "REGIONAL")
        ],
        meta=build_meta(data_status="PUBLISHED"),
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
