"""Schema for ``config/synthetic.yaml`` — parameters of the labelled synthetic dataset.

The synthetic generator (:mod:`apix_core.testing.synthetic`) is validation
infrastructure: it produces data with the statistical shape of real Indian airfares so
the cleaning and index layers can be proven end to end without touching a live website.
Every number in the YAML is a **scenario parameter**, not an observation. Nothing here
is, or may ever be presented as, collected data — which is why source codes are forced
to carry the ``synthetic_`` prefix at schema level.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_DOW_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class AnomalyKind(StrEnum):
    """Deliberate defects the watchdog and cleaning layers are expected to catch."""

    PRICE_SPIKE = "PRICE_SPIKE"  # one quote multiplied far above its neighbours
    FAT_FINGER = "FAT_FINGER"  # one quote divided by a power of ten
    STALE_REPEAT = "STALE_REPEAT"  # a cell frozen across collection days
    COMPONENT_MISMATCH = "COMPONENT_MISMATCH"  # total no longer equals its parts


class LeadTimeKnot(BaseModel):
    """One point on the advance-purchase price curve.

    The curve is interpolated log-linearly between knots, so the whole booking-curve
    shape — flat far out, gentle rise, steep walk-up — is data, not code.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    days_before_departure: int = Field(ge=0, le=365)
    multiplier: float = Field(gt=0)


class Festival(BaseModel):
    """A demand surge window around one calendar date.

    Dates are scenario parameters chosen to fall inside the generated window; they are
    maintained by hand and must be re-checked if the scenario year changes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    date: date
    surge: float = Field(ge=1)
    days_before: int = Field(ge=0, le=30)
    days_after: int = Field(ge=0, le=30)


class CarrierParams(BaseModel):
    """Per-carrier pricing level and how often the carrier appears on a route."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fare_factor: float = Field(gt=0)
    presence_weight: float = Field(gt=0)


class PricingConfig(BaseModel):
    """Base-price surface and the Indian fare component structure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_floor_inr: float = Field(gt=0)
    price_per_km_inr: float = Field(gt=0)
    route_effect_sigma: float = Field(ge=0)  # fixed per route-carrier, lognormal
    daily_noise_sigma: float = Field(ge=0)  # redrawn every (flight, travel day, query day)
    tax_rate: float = Field(ge=0, le=1)  # percentage tax on the base fare
    udf_default_inr: float = Field(ge=0)  # user development fee, per origin airport
    udf_overrides_inr: dict[str, float] = Field(default_factory=dict)

    @field_validator("udf_overrides_inr")
    @classmethod
    def _iata_keys(cls, value: dict[str, float]) -> dict[str, float]:
        bad = [k for k in value if len(k) != 3 or not k.isupper()]
        if bad:
            raise ValueError(f"udf_overrides_inr keys must be IATA airport codes: {bad}")
        if any(v < 0 for v in value.values()):
            raise ValueError("udf_overrides_inr values must be >= 0")
        return value


class BucketConfig(BaseModel):
    """Fare-bucket ladder driving sell-out behaviour.

    Each flight departure has ``count`` nested buckets. Bucket ``k`` is priced
    ``(1 + price_step)^k`` over the filed fare and closes — permanently, per departure —
    around ``close_days_mu[k]`` days before departure. When every bucket is closed the
    departure is sold out and no quote is emitted: the missing observation is the point.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    count: int = Field(ge=2, le=26)
    price_step: float = Field(gt=0)
    close_days_mu: list[float] = Field(min_length=2)
    close_days_sigma: float = Field(ge=0)
    # How strongly demand surges (festival, weekend) pull closures earlier in time
    # (i.e. to a larger days-before-departure value).
    demand_sensitivity: float = Field(ge=0)

    @model_validator(mode="after")
    def _ladder_is_coherent(self) -> BucketConfig:
        if len(self.close_days_mu) != self.count:
            raise ValueError("close_days_mu must have exactly `count` entries")
        if any(b > a for a, b in zip(self.close_days_mu, self.close_days_mu[1:], strict=False)):
            raise ValueError(
                "close_days_mu must be non-increasing: cheaper buckets close further from departure"
            )
        if any(v < 0 for v in self.close_days_mu):
            raise ValueError("close_days_mu entries must be >= 0")
        return self


class SyntheticSource(BaseModel):
    """A pretend sales channel. The ``synthetic_`` prefix is not negotiable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(min_length=1, max_length=32)
    display_name: str = Field(min_length=1, max_length=128)
    convenience_fee_inr: float = Field(ge=0)  # per-channel booking fee, OTA-style

    @field_validator("code")
    @classmethod
    def _labelled_synthetic(cls, value: str) -> str:
        if not value.startswith("synthetic_"):
            raise ValueError(
                f"synthetic source code {value!r} must start with 'synthetic_': the "
                "label is what keeps generated rows unmistakable in the database"
            )
        return value


class CollectionShape(BaseModel):
    """How the pretend collector samples the fare surface."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Days before departure at which each route is priced on every collection day.
    # Chosen to hit every advance window in config/basket.yaml.
    advance_days_grid: list[int] = Field(min_length=1)
    flights_per_route_carrier: int = Field(ge=1, le=6)
    carriers_per_route_min: int = Field(ge=1, le=8)
    carriers_per_route_max: int = Field(ge=1, le=8)
    collection_hour_ist: int = Field(ge=0, le=23)

    @model_validator(mode="after")
    def _grid_and_range(self) -> CollectionShape:
        if sorted(set(self.advance_days_grid)) != list(self.advance_days_grid):
            raise ValueError("advance_days_grid must be strictly increasing and unique")
        if any(d < 0 or d > 365 for d in self.advance_days_grid):
            raise ValueError("advance_days_grid entries must be within 0..365")
        if self.carriers_per_route_max < self.carriers_per_route_min:
            raise ValueError("carriers_per_route_max must be >= carriers_per_route_min")
        return self


class AnomalySpec(BaseModel):
    """How many defects of one kind to inject, and how hard."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: AnomalyKind
    count: int = Field(ge=0, le=10_000)
    # PRICE_SPIKE: multiplier; FAT_FINGER: divisor; COMPONENT_MISMATCH: INR added to
    # total_fare only; STALE_REPEAT: ignored (run_length_days governs).
    magnitude: float = Field(gt=0)
    run_length_days: int = Field(default=5, ge=2, le=30)  # STALE_REPEAT only


class SyntheticConfig(BaseModel):
    """The whole ``config/synthetic.yaml`` file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1, max_length=32)
    seed: int = Field(ge=0)
    description: str = ""

    pricing: PricingConfig
    carriers: dict[str, CarrierParams] = Field(min_length=1)
    lead_time_knots: list[LeadTimeKnot] = Field(min_length=2)
    dow_multipliers: dict[str, float]
    festivals: list[Festival] = Field(default_factory=list)
    buckets: BucketConfig
    sources: list[SyntheticSource] = Field(min_length=1)
    collection: CollectionShape
    anomalies: list[AnomalySpec] = Field(default_factory=list)

    @field_validator("carriers")
    @classmethod
    def _carrier_keys(cls, value: dict[str, CarrierParams]) -> dict[str, CarrierParams]:
        bad = [k for k in value if len(k) != 2]
        if bad:
            raise ValueError(f"carrier keys must be 2-character IATA designators: {bad}")
        return value

    @field_validator("dow_multipliers")
    @classmethod
    def _all_seven_days(cls, value: dict[str, float]) -> dict[str, float]:
        if tuple(value) != _DOW_KEYS and set(value) != set(_DOW_KEYS):
            raise ValueError(f"dow_multipliers must have exactly the keys {_DOW_KEYS}")
        if any(v <= 0 for v in value.values()):
            raise ValueError("dow_multipliers must be > 0")
        return value

    @model_validator(mode="after")
    def _coherent(self) -> SyntheticConfig:
        days = [k.days_before_departure for k in self.lead_time_knots]
        if sorted(set(days), reverse=True) != days:
            raise ValueError("lead_time_knots must be strictly decreasing in days_before_departure")
        codes = [s.code for s in self.sources]
        if len(set(codes)) != len(codes):
            raise ValueError(f"duplicate synthetic source codes: {codes}")
        if self.collection.carriers_per_route_max > len(self.carriers):
            raise ValueError("carriers_per_route_max exceeds the number of carriers defined")
        kinds = [a.kind for a in self.anomalies]
        if len(set(kinds)) != len(kinds):
            raise ValueError("at most one AnomalySpec per kind; adjust count instead")
        return self

    def dow_multiplier_vector(self) -> list[float]:
        """Multipliers ordered Monday..Sunday, aligned with ``date.weekday()``."""
        return [self.dow_multipliers[k] for k in _DOW_KEYS]

    def udf_for(self, origin_iata: str) -> Decimal:
        """UDF charged at ``origin_iata``, as money."""
        value = self.pricing.udf_overrides_inr.get(origin_iata, self.pricing.udf_default_inr)
        return Decimal(str(round(value, 2)))


__all__ = [
    "AnomalyKind",
    "AnomalySpec",
    "BucketConfig",
    "CarrierParams",
    "CollectionShape",
    "Festival",
    "LeadTimeKnot",
    "PricingConfig",
    "SyntheticConfig",
    "SyntheticSource",
]
