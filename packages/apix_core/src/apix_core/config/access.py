"""Schema for ``config/access.yaml`` — per-role rate limits for the public API.

Rate-limit tiers are policy, not code: changing what a researcher key is entitled to
should not require a deploy. Kept separate from ``config/method.yaml`` and
``config/cleaning.yaml`` — this governs API access, not the index itself.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RoleLimit(BaseModel):
    """Token-bucket limits for one role."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requests_per_minute: int = Field(gt=0)
    burst: int = Field(gt=0)


class AccessConfig(BaseModel):
    """The whole ``config/access.yaml`` file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1, max_length=32)
    description: str = ""

    public: RoleLimit
    researcher: RoleLimit
    official: RoleLimit


__all__ = ["AccessConfig", "RoleLimit"]
