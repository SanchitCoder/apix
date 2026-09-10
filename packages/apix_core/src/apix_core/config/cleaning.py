"""Schema for ``config/cleaning.yaml`` — parameters for :mod:`apix_core.clean`.

Distinct from ``config/method.yaml``: this file governs how a raw ``fare_quote`` row
becomes a ``fare_quote_clean`` row (decomposition, outlier screening, sell-out
imputation, quality gates), not the index maths applied on top of the clean table.
Changing a value here changes which observations are flagged, imputed or gated, so —
like every other config file — it is validated on load and its content is deterministic.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OutlierRuleName(StrEnum):
    """Which outlier screen is active. Both are always computable; only one gates."""

    MAD_LOG = "mad_log"  # median absolute deviation on log(total_fare)
    IQR = "iqr"  # inter-quartile range on log(total_fare)


class DedupConfig(BaseModel):
    """Stage 1 — matching the same physical flight across sources."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dep_time_tolerance_minutes: int = Field(ge=0, le=180)


class DecompositionConfig(BaseModel):
    """Stage 2 — deriving base/taxes/UDF for sources that only publish a total."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Published tax rate applied to the derived base fare. A methodology parameter
    # (e.g. the GST rate for the fare class the basket collects), not a guess.
    tax_rate: float = Field(ge=0, le=1)


class OutlierConfig(BaseModel):
    """Stage 3 — screening rules, and which one is active."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_rule: OutlierRuleName
    mad_threshold: float = Field(gt=0)
    iqr_k: float = Field(gt=0)
    # Cells smaller than this are never screened: there is not enough spread to tell a
    # genuine outlier from a small sample, so flagging one would be a guess.
    min_cell_size: int = Field(ge=2)


class ImputationConfig(BaseModel):
    """Stage 4 — cell-mean imputation for genuine sell-outs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sellout_group_columns: list[str] = Field(min_length=1)
    min_group_size: int = Field(ge=1)


class DistanceBand(BaseModel):
    """One route-distance band and its plausible ``base_fare`` range."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=32)
    # Exclusive upper bound in kilometres; null means "no upper bound" (the last band).
    max_km: float | None = Field(default=None, gt=0)
    base_fare_min_inr: float = Field(ge=0)
    base_fare_max_inr: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> DistanceBand:
        if self.base_fare_max_inr <= self.base_fare_min_inr:
            raise ValueError(f"band {self.name}: base_fare_max_inr must exceed base_fare_min_inr")
        return self


class QualityGateConfig(BaseModel):
    """Thresholds enforced by :mod:`apix_core.clean.gates` before every index run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    distance_bands: list[DistanceBand] = Field(min_length=1)
    tax_share_min: float = Field(ge=0, le=1)
    tax_share_max: float = Field(ge=0, le=1)
    coverage_floor_pct: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _coherent(self) -> QualityGateConfig:
        if self.tax_share_max <= self.tax_share_min:
            raise ValueError("tax_share_max must exceed tax_share_min")
        finite = [b for b in self.distance_bands if b.max_km is not None]
        unbounded = [b for b in self.distance_bands if b.max_km is None]
        if len(unbounded) != 1:
            raise ValueError("distance_bands must have exactly one unbounded (max_km: null) band")
        if unbounded[0] is not self.distance_bands[-1]:
            raise ValueError("the unbounded distance band must be listed last")
        km_values = [b.max_km for b in finite if b.max_km is not None]
        if km_values != sorted(km_values):
            raise ValueError("distance_bands must be listed in increasing max_km order")
        return self

    def band_for_distance(self, distance_km: float) -> DistanceBand:
        for band in self.distance_bands:
            if band.max_km is None or distance_km < band.max_km:
                return band
        raise AssertionError("unreachable: the last band is always unbounded")


class CleaningConfig(BaseModel):
    """The whole ``config/cleaning.yaml`` file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1, max_length=32)
    description: str = ""

    dedup: DedupConfig
    decomposition: DecompositionConfig
    outliers: OutlierConfig
    imputation: ImputationConfig
    quality_gates: QualityGateConfig


__all__ = [
    "CleaningConfig",
    "DecompositionConfig",
    "DedupConfig",
    "DistanceBand",
    "ImputationConfig",
    "OutlierConfig",
    "OutlierRuleName",
    "QualityGateConfig",
]
