"""Schema for ``config/basket.yaml`` — the route basket and its weights."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ROUTE_CODE_RE = re.compile(r"^[A-Z]{3}-[A-Z]{3}$")


class AdvanceWindow(BaseModel):
    """One advance-purchase stratum, in days before departure.

    Fares are collected and indexed within these windows because the same seat has a
    different price depending on how far ahead it is bought; mixing windows would make
    the index a measure of booking behaviour rather than of price.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(min_length=1, max_length=16)
    min_days: int = Field(ge=0, le=365)
    max_days: int = Field(ge=0, le=365)
    label: str

    @model_validator(mode="after")
    def _ordered(self) -> AdvanceWindow:
        if self.max_days < self.min_days:
            raise ValueError(f"window {self.code}: max_days must be >= min_days")
        return self


class RouteEntry(BaseModel):
    """One directional city-pair in the basket."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    origin: str = Field(min_length=3, max_length=3)
    dest: str = Field(min_length=3, max_length=3)
    # None until Phase 2 loads the real DGCA figures. Never guessed, never defaulted.
    dgca_pax_share: Decimal | None = Field(default=None, ge=0, le=1)
    active_from: date
    active_to: date | None = None

    @field_validator("code")
    @classmethod
    def _code_shape(cls, value: str) -> str:
        if not ROUTE_CODE_RE.match(value):
            raise ValueError(f"route code {value!r} must look like 'DEL-BOM'")
        return value

    @model_validator(mode="after")
    def _code_matches_endpoints(self) -> RouteEntry:
        if self.code != f"{self.origin}-{self.dest}":
            raise ValueError(f"route code {self.code!r} does not match {self.origin}/{self.dest}")
        if self.origin == self.dest:
            raise ValueError(f"route {self.code}: origin and destination are the same airport")
        if self.active_to is not None and self.active_to <= self.active_from:
            raise ValueError(f"route {self.code}: active_to must be after active_from")
        return self


class BasketConfig(BaseModel):
    """The whole basket file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    basket_version: str = Field(min_length=1, max_length=32)
    effective_from: date
    description: str = ""
    advance_windows: list[AdvanceWindow] = Field(min_length=1)
    routes: list[RouteEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_and_consistent(self) -> BasketConfig:
        codes = [r.code for r in self.routes]
        duplicates = {c for c in codes if codes.count(c) > 1}
        if duplicates:
            raise ValueError(f"duplicate route codes in basket: {sorted(duplicates)}")

        window_codes = [w.code for w in self.advance_windows]
        dup_windows = {c for c in window_codes if window_codes.count(c) > 1}
        if dup_windows:
            raise ValueError(f"duplicate advance window codes: {sorted(dup_windows)}")

        # Shares are optional, but if any are supplied they must be a coherent
        # distribution: a half-populated weight vector would silently bias the index.
        shares = [r.dgca_pax_share for r in self.routes]
        supplied = [s for s in shares if s is not None]
        if supplied and len(supplied) != len(shares):
            raise ValueError(
                "dgca_pax_share is set on some routes but not all. Populate every route "
                "from the DGCA release or leave them all null."
            )
        if supplied and sum(supplied) > Decimal("1"):
            raise ValueError("dgca_pax_share values sum to more than 1")
        return self

    @property
    def weights_are_populated(self) -> bool:
        """True once Phase 2 has loaded real DGCA passenger shares."""
        return all(r.dgca_pax_share is not None for r in self.routes)


__all__ = ["AdvanceWindow", "BasketConfig", "RouteEntry"]
