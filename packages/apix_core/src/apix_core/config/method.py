"""Schema for ``config/method.yaml`` — the index method, as data.

Changing any value in this file changes the published number, so the file is hashed and
the hash is stamped onto every index run. ``docs/methodology.md`` is generated from a
validated instance of this schema; it is never written by hand.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ElementaryFormula(StrEnum):
    """Formula for the lowest-level aggregate, below the level of weights."""

    JEVONS = "jevons"  # geometric mean of price relatives
    DUTOT = "dutot"  # ratio of arithmetic means
    CARLI = "carli"  # arithmetic mean of price relatives — biased, present for testing


class MultilateralMethod(StrEnum):
    """Multilateral method used across the rolling window."""

    GEKS_TORNQVIST = "geks_tornqvist"
    GEKS_FISHER = "geks_fisher"
    TIME_PRODUCT_DUMMY = "time_product_dummy"
    GEARY_KHAMIS = "geary_khamis"


class SpliceMethod(StrEnum):
    """How consecutive windows are joined into a continuous series.

    Whichever method is configured, splicing only ever appends the newest period: a
    published value is never revised by rolling the window forward (CLAUDE.md
    principle 4). See :mod:`apix_core.index.splice` for the formulas.
    """

    MOVEMENT = "movement"
    WINDOW = "window"
    HALF = "half"
    MEAN = "mean"  # mean splice (Diewert & Fox) — the pure-function default
    FBEW = "fbew"  # fixed base expanding window
    FBMW = "fbmw"  # fixed base moving window


class ImputationRule(StrEnum):
    """What to do about a missing elementary cell."""

    NONE = "none"  # leave the gap; the cell is recorded as missing
    CARRY_FORWARD = "carry_forward"  # always sets is_imputed and imputation_method
    CLASS_MEAN = "class_mean"
    TARGETED_MEAN = "targeted_mean"


class OutlierRule(BaseModel):
    """One outlier screen. Dropped observations are flagged, never deleted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    method: str = Field(min_length=1, max_length=32)
    threshold: float = Field(gt=0)
    applies_to: str = "total_fare"


class WindowConfig(BaseModel):
    """Rolling window over which the multilateral index is estimated."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    length_periods: int = Field(ge=2, le=48)
    frequency: str = Field(default="M", pattern=r"^[DWMQA]$")


class QualityAdjustment(BaseModel):
    """Hedonic quality adjustment settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True
    # Characteristics entering the hedonic regression. Each must be a column present
    # on fare_quote_clean or derivable from it without further collection.
    columns: list[str] = Field(min_length=1)
    model: str = Field(default="time_dummy_hedonic", max_length=64)
    min_observations: int = Field(default=30, ge=1)
    # Below this R-squared, apix_core.index.hedonic refuses to publish the
    # quality-adjusted index and raises rather than returning a number nobody checked.
    min_r_squared: float = Field(default=0.3, ge=0.0, le=1.0)


class BookingProfile(BaseModel):
    """Weights combining the advance-purchase windows into one route index.

    ``weights`` must be sourced from real booking-profile data (ticket sales by
    advance-purchase window). Until that data exists, the shipped ``config/method.yaml``
    uses a stated, documented assumption — never a silent guess — and ``source`` must
    say so explicitly. See ``docs/methodology.md``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1, max_length=200)
    weights: dict[str, float] = Field(min_length=1)

    @model_validator(mode="after")
    def _weights_are_a_valid_distribution(self) -> BookingProfile:
        if any(w < 0 for w in self.weights.values()):
            raise ValueError("booking_profile weights must be non-negative")
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"booking_profile weights must sum to 1.0, got {total}")
        return self


class MethodConfigFile(BaseModel):
    """The whole method file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method_version: str = Field(min_length=1, max_length=32)
    description: str = ""
    price_reference_period: str = Field(pattern=r"^\d{4}-\d{2}$")
    index_reference_value: float = Field(default=100.0, gt=0)

    elementary_formula: ElementaryFormula
    multilateral_method: MultilateralMethod
    window: WindowConfig
    splice_method: SpliceMethod
    quality_adjustment: QualityAdjustment
    booking_profile: BookingProfile
    imputation_rule: ImputationRule
    outlier_rules: list[OutlierRule] = Field(default_factory=list)

    min_quotes_per_cell: int = Field(default=5, ge=1)
    min_coverage_pct: float = Field(default=60.0, ge=0.0, le=100.0)

    @model_validator(mode="after")
    def _coherent(self) -> MethodConfigFile:
        if self.elementary_formula is ElementaryFormula.CARLI:
            # Carli fails the time-reversal test and is upward-biased. It stays in the
            # enum so it can be computed for comparison, but it cannot be the published
            # method: a national statistics office would reject the series.
            raise ValueError(
                "carli is not permitted as the published elementary formula; it is "
                "biased and fails the time-reversal test. Use jevons or dutot."
            )
        names = [r.name for r in self.outlier_rules]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"duplicate outlier rule names: {sorted(duplicates)}")
        return self


__all__ = [
    "BookingProfile",
    "ElementaryFormula",
    "ImputationRule",
    "MethodConfigFile",
    "MultilateralMethod",
    "OutlierRule",
    "QualityAdjustment",
    "SpliceMethod",
    "WindowConfig",
]
