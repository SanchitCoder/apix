"""Pydantic v2 response models. These are the API contract.

Nothing here touches the database. A schema change here is a breaking change to the
front end and to any SDMX consumer, so it goes through the same review as a method
change.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from apix_api.pagination import ResponseMeta
from apix_core.config.method import (
    ElementaryFormula,
    ImputationRule,
    MultilateralMethod,
    SpliceMethod,
)

# --------------------------------------------------------------------- health ----


class HealthResponse(BaseModel):
    """Liveness. Answers only whether this process is running."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    service: str = "apix-api"
    version: str


class DependencyStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    ok: bool
    detail: str | None = None


class ReadyResponse(BaseModel):
    """Readiness. Answers "can this process serve traffic", dependency by dependency."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "degraded", "not_ready"]
    dependencies: list[DependencyStatus]


# ---------------------------------------------------------------------- index ----


class IndexPoint(BaseModel):
    """One published index observation.

    ``n_quotes`` and ``coverage_pct`` are mandatory companions of ``value``: a published
    number travels with the evidence base behind it.
    """

    model_config = ConfigDict(extra="forbid")

    series: str = Field(description="Series code, e.g. APIX.ALL.M.")
    period: date = Field(description="First day of the period the value refers to.")
    value: float = Field(description="Index value; reference period = 100.")
    n_quotes: int = Field(ge=0, description="Cleaned quotes underlying this value.")
    coverage_pct: float | None = Field(
        default=None, ge=0, le=100, description="Share of basket routes with data."
    )
    is_imputed: bool = Field(default=False, description="True if any input cell was imputed.")
    status: Literal["PROVISIONAL", "PUBLISHED", "REVISED", "SUPPRESSED", "EXAMPLE_ONLY"] = (
        "EXAMPLE_ONLY"
    )


class VintageValue(BaseModel):
    """A period's value as it stood at a given vintage date."""

    model_config = ConfigDict(extra="forbid")

    series: str
    period: date
    as_of: date = Field(description="Vintage date the value is reported as of.")
    value: float
    index_run_id: str
    revised_from: float | None = Field(
        default=None, description="Previous value, if this vintage was a revision."
    )
    revision_reason: str | None = None


# --------------------------------------------------------------------- routes ----


class RouteSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Directional route code, e.g. DEL-BOM.")
    origin_iata: str
    origin_city: str
    dest_iata: str
    dest_city: str
    dgca_pax_share: float | None = Field(
        default=None,
        description=(
            "Route's share of DGCA-reported domestic passengers. Null until Phase 2 "
            "loads the real DGCA release; never estimated."
        ),
    )
    basket_version: str
    active_from: date
    active_to: date | None = None
    origin_lat: float | None = Field(
        default=None,
        description="Origin airport latitude (db/seeds/airports.csv). Null when not yet joined.",
    )
    origin_lon: float | None = None
    dest_lat: float | None = None
    dest_lon: float | None = None


class RouteSeriesPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: date
    advance_days: int = Field(ge=0, le=365)
    carrier_iata: str | None = Field(
        default=None, description="Carrier the point is restricted to. Null = all carriers."
    )
    mean_fare: float
    median_fare: float
    p25_fare: float
    p75_fare: float
    n_quotes: int = Field(ge=0)
    sold_out: bool = Field(
        default=False,
        description=(
            "True when every observed itinerary in the cell was sold out. The fare "
            "fields then describe the last quotes seen before sell-out, not a bookable "
            "price, and the dashboard must shade the period rather than plot it as one."
        ),
    )
    currency: str = "INR"


# ------------------------------------------------------------------- leadtime ----


class LeadTimeBucket(BaseModel):
    """Mean fare by how far ahead the ticket is priced — the lead-time curve."""

    model_config = ConfigDict(extra="forbid")

    window_code: str = Field(description="Advance-purchase window from config/basket.yaml.")
    min_days: int
    max_days: int
    mean_fare: float
    median_fare: float
    p25_fare: float = Field(description="Lower quartile — the dispersion band the chart draws.")
    p75_fare: float = Field(description="Upper quartile — the dispersion band the chart draws.")
    n_quotes: int = Field(ge=0)
    index_vs_cheapest: float = Field(
        description="Mean fare relative to the cheapest window in the same route, = 100."
    )


class LeadTimeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_code: str
    carrier_iata: str | None = Field(
        default=None, description="Carrier the curve is restricted to. Null = all carriers."
    )
    currency: str = "INR"
    buckets: list[LeadTimeBucket]
    meta: ResponseMeta


# -------------------------------------------------------------------- heatmap ----


class HeatmapCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_code: str
    period: date
    value: float = Field(description="Index value for this route and period.")
    n_quotes: int = Field(ge=0)


# -------------------------------------------------------------- decomposition ----


class DecompositionComponent(BaseModel):
    """One additive contribution to the period-on-period index movement."""

    model_config = ConfigDict(extra="forbid")

    component: str = Field(
        description=(
            "base_fare | taxes | udf | convenience_fee | mix_route | mix_carrier | "
            "mix_advance_window | quality_adjustment | residual"
        )
    )
    contribution_pct_points: float = Field(
        description="Percentage-point contribution to the total movement."
    )
    share_of_movement: float = Field(description="Signed share of the total movement.")


class DecompositionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: date
    series: str
    total_movement_pct: float
    components: list[DecompositionComponent]
    residual_pct_points: float = Field(
        description="Unexplained remainder. Reported, never distributed across components."
    )
    meta: ResponseMeta


# -------------------------------------------------------------------- nowcast ----


class NowcastPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_series: str
    target_period: date
    point_estimate: float
    ci_low: float | None = None
    ci_high: float | None = None
    ci_level: float = Field(default=0.80, gt=0, lt=1, description="Credible interval level.")
    model_version: str
    produced_at: str
    caveat: str = Field(
        default=(
            "A nowcast is a model estimate of a period that has not closed. It is not a "
            "published index value and must not be cited as one."
        )
    )


# ------------------------------------------------------------------- coverage ----


class SourceCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_code: str
    status: Literal["OK", "PARTIAL", "BLOCKED", "DISABLED", "ERROR"]
    quotes_collected: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    reason: str | None = Field(
        default=None, description="Why a source is not OK. Never null when status is not OK."
    )


class CoverageResponse(BaseModel):
    """What was actually collected on a date, including what was not.

    An empty result is data. ``routes_missing`` is a list, not an omission.
    """

    model_config = ConfigDict(extra="forbid")

    date: date
    routes_expected: int
    routes_covered: int
    coverage_pct: float = Field(ge=0, le=100)
    routes_missing: list[str]
    sources: list[SourceCoverage]
    meta: ResponseMeta


# ------------------------------------------------------------------- metadata ----


class AdvanceWindowOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    min_days: int
    max_days: int
    label: str


class BasketMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    basket_version: str
    effective_from: date
    description: str
    n_routes: int
    weights_populated: bool = Field(
        description="False until Phase 2 loads DGCA passenger shares for every route."
    )
    advance_windows: list[AdvanceWindowOut]
    routes: list[RouteSummary]


class CarrierOut(BaseModel):
    """One scheduled domestic carrier, as classified by APIx."""

    model_config = ConfigDict(extra="forbid")

    iata: str = Field(min_length=2, max_length=2)
    icao: str
    name: str
    carrier_type: Literal["FSC", "LCC", "REGIONAL"]


class CarriersMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    carriers: list[CarrierOut]
    meta: ResponseMeta


class MethodMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method_version: str
    config_hash: str = Field(description="SHA-256 of the canonical method config.")
    description: str
    price_reference_period: str
    index_reference_value: float
    elementary_formula: str
    multilateral_method: str
    window_length_periods: int
    window_frequency: str
    splice_method: str
    quality_adjustment_enabled: bool
    quality_adjustment_columns: list[str]
    imputation_rule: str
    outlier_rules: list[dict[str, Any]]
    min_quotes_per_cell: int
    min_coverage_pct: float


# ----------------------------------------------------------------- provenance ----


class ProvenanceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_code: str
    display_name: str
    domain: str
    source_type: str
    collection_method: str
    legal_basis: str
    policy_decision: str = Field(description="The PolicyEngine outcome that permitted the fetch.")
    robots_fetched_at: str | None = None
    tos_verdict: str
    tos_reviewed_at: str | None = None


class ProvenanceTreatment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clean_id: str
    is_outlier: bool
    outlier_rule: str | None
    is_imputed: bool
    imputation_method: str | None
    quality_vector: dict[str, Any]


class ProvenanceResponse(BaseModel):
    """The full chain: quote -> source and legal basis -> cleaning -> index values.

    This endpoint is the operational form of principle 1. If it cannot answer, the
    number should not have been published.
    """

    model_config = ConfigDict(extra="forbid")

    quote_id: str
    collected_at: str
    run_id: str
    route_code: str
    carrier_iata: str
    travel_date: date
    query_date: date
    advance_days: int
    total_fare: float
    currency: str
    source_url_hash: str
    content_hash: str
    raw_payload_ref: str | None
    source: ProvenanceSource
    treatment: ProvenanceTreatment | None
    contributed_to: list[str] = Field(
        description="Series codes and periods this quote contributed to."
    )
    meta: ResponseMeta


# -------------------------------------------------------------------- drill-down ----


class RouteContribution(BaseModel):
    """One route's part in a headline index value — audit drill-down, level 2.

    ``weight`` and ``contribution_pct_points`` are null until Phase 2 attaches DGCA
    passenger shares; an unweighted contribution is reported as absent, never estimated.
    """

    model_config = ConfigDict(extra="forbid")

    route_code: str
    series: str = Field(description="The route-level series code, e.g. APIX.ROUTE.DEL-BOM.M.")
    period: date
    index_value: float
    weight: float | None = None
    contribution_pct_points: float | None = None
    n_quotes: int = Field(ge=0)


class QuoteSummary(BaseModel):
    """One cleaned observation behind a route index value — audit drill-down, level 3.

    Each row resolves further through ``/v1/provenance/{quote_id}``.
    """

    model_config = ConfigDict(extra="forbid")

    quote_id: str = Field(description="fare_quote.id — the key into /v1/provenance.")
    clean_id: str | None = Field(
        default=None, description="fare_quote_clean.id. Null when the quote was screened out."
    )
    route_code: str
    carrier_iata: str
    travel_date: date
    query_date: date
    advance_days: int = Field(ge=0)
    total_fare: float
    currency: str = "INR"
    source_code: str
    is_outlier: bool
    outlier_rule: str | None = None
    is_imputed: bool
    imputation_method: str | None = None


class RevisionEntry(BaseModel):
    """One row of the revision log. Revisions are visible, never silent."""

    model_config = ConfigDict(extra="forbid")

    revised_at: str = Field(description="RFC 3339 timestamp of the revision.")
    series: str
    period: date
    old_value: float | None = Field(
        default=None, description="Null when the entry is a first publication, not a revision."
    )
    new_value: float
    reason: str
    index_run_id: str


# ------------------------------------------------------------------- method preview ----


class MethodOverrides(BaseModel):
    """Request body for a preview run: the method in force, with these fields changed.

    Every field is optional; an omitted field keeps the value from ``config/method.yaml``.
    The merged configuration is re-validated by the same schema that validates the file,
    so a preview cannot request a method the system would refuse to publish (e.g. a Carli
    elementary aggregate).
    """

    model_config = ConfigDict(extra="forbid")

    elementary_formula: ElementaryFormula | None = None
    multilateral_method: MultilateralMethod | None = None
    window_length_periods: int | None = Field(default=None, ge=2, le=48)
    splice_method: SpliceMethod | None = None
    quality_adjustment_enabled: bool | None = None
    imputation_rule: ImputationRule | None = None


class MethodPreviewSettings(BaseModel):
    """The fully-resolved method configuration a preview was computed under."""

    model_config = ConfigDict(extra="forbid")

    elementary_formula: ElementaryFormula
    multilateral_method: MultilateralMethod
    window_length_periods: int
    splice_method: SpliceMethod
    quality_adjustment_enabled: bool
    imputation_rule: ImputationRule


class MethodPreviewPoint(BaseModel):
    """One period of a preview run, next to the value the method in force produces."""

    model_config = ConfigDict(extra="forbid")

    period: date
    value: float
    baseline_value: float = Field(description="Same period under the method in force.")
    n_quotes: int = Field(ge=0)
    coverage_pct: float | None = Field(default=None, ge=0, le=100)
    imputed_cells: int = Field(ge=0)
    outlier_cells: int = Field(ge=0, description="Observations dropped by outlier screens.")


class MethodPreviewDiagnostics(BaseModel):
    """Aggregate quality indicators for a preview run, shown beside the chart."""

    model_config = ConfigDict(extra="forbid")

    coverage_pct: float = Field(ge=0, le=100)
    n_quotes: int = Field(ge=0)
    imputed_cell_count: int = Field(ge=0)
    outlier_dropped_count: int = Field(ge=0)
    suppressed_cell_count: int = Field(
        ge=0, description="Cells below publication thresholds — suppressed, not dropped."
    )


class MethodPreviewResponse(BaseModel):
    """A preview index run. Never a published statistic, and labelled so.

    ``config_hash`` is the hash the previewed configuration *would* be stamped with,
    so a preview a statistician decides to adopt is traceable to the exact config that
    produced it.
    """

    model_config = ConfigDict(extra="forbid")

    series: str
    preview_run_id: str
    is_baseline: bool = Field(
        description="True when the resolved settings equal the method in force."
    )
    settings: MethodPreviewSettings
    config_hash: str = Field(description="SHA-256 of the previewed method configuration.")
    baseline_config_hash: str = Field(description="SHA-256 of the method in force.")
    points: list[MethodPreviewPoint]
    diagnostics: MethodPreviewDiagnostics
    meta: ResponseMeta


# ----------------------------------------------------------------------- sdmx ----


class SdmxMessage(BaseModel):
    """SDMX-JSON 2.0.0 data message.

    Modelled loosely on purpose: the SDMX information model is deep, and pinning it into
    Pydantic here would freeze parts of it we do not yet emit. The envelope keys are
    fixed; their contents follow the SDMX-JSON 2.0.0 specification.
    """

    model_config = ConfigDict(extra="allow")

    meta: dict[str, Any]
    data: dict[str, Any]
