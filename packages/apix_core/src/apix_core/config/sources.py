"""Schema for ``config/sources.yaml`` — one entry per source, mirroring source_policy.

This file is the reviewed compliance position for every site APIx touches. It is the
input that seeds ``source`` and ``source_policy``; the PolicyEngine reads the database,
not this file, but the two must agree.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apix_core.models.enums import LegalBasis, SourceType, TosVerdict


class SourcePolicyConfig(BaseModel):
    """Every field of the ``source_policy`` table, in reviewable form."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    robots_url: str | None = None
    allowed_paths: list[str] = Field(default_factory=list)
    disallowed_paths: list[str] = Field(default_factory=list)
    crawl_delay_s: float = Field(default=2.0, ge=0.0, le=3600.0)
    max_requests_per_hour: int = Field(default=60, ge=1, le=100_000)
    tos_url: str | None = None
    tos_reviewed_at: datetime | None = None
    tos_verdict: TosVerdict = TosVerdict.NOT_REVIEWED
    legal_basis: LegalBasis | None = None

    @model_validator(mode="after")
    def _reviewed_verdicts_carry_evidence(self) -> SourcePolicyConfig:
        if self.tos_verdict is not TosVerdict.NOT_REVIEWED:
            if self.tos_url is None:
                raise ValueError("a reviewed tos_verdict requires tos_url")
            if self.tos_reviewed_at is None:
                raise ValueError("a reviewed tos_verdict requires tos_reviewed_at")
        return self


class SourceEntry(BaseModel):
    """One source and its policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9_]+$")
    display_name: str
    domain: str = Field(min_length=3, max_length=255)
    source_type: SourceType
    enabled: bool = False
    policy: SourcePolicyConfig

    @model_validator(mode="after")
    def _enabling_requires_a_permitted_basis(self) -> SourceEntry:
        """A source cannot be switched on without a reviewed, permissive basis.

        AMBIGUOUS is treated as prohibited. This is the config-time half of the
        guardrail; the PolicyEngine enforces the same rule at request time.
        """
        if not self.enabled:
            return self
        if self.policy.tos_verdict is not TosVerdict.PERMITTED:
            raise ValueError(
                f"source {self.code!r} is enabled but tos_verdict is "
                f"{self.policy.tos_verdict}. Only PERMITTED sources may be enabled."
            )
        if self.policy.legal_basis is None:
            raise ValueError(f"source {self.code!r} is enabled but has no legal_basis")
        return self


class SourcesConfig(BaseModel):
    """The whole sources file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1, max_length=32)
    sources: list[SourceEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def _codes_are_unique(self) -> SourcesConfig:
        codes = [s.code for s in self.sources]
        duplicates = {c for c in codes if codes.count(c) > 1}
        if duplicates:
            raise ValueError(f"duplicate source codes: {sorted(duplicates)}")
        return self

    @property
    def enabled_codes(self) -> list[str]:
        return [s.code for s in self.sources if s.enabled]


__all__ = ["SourceEntry", "SourcePolicyConfig", "SourcesConfig"]
