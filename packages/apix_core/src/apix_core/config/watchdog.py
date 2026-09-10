"""Schema for ``config/watchdog.yaml`` — the market-integrity watchdog.

Governs four independent checks: the personalised-pricing probe, surge detection,
sell-out velocity, and rail-fare substitution. None of these can change a published
``index_value`` — they are diagnostic, not part of the index method.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Hard ceiling on probe frequency: the personalised-pricing probe is explicitly a
# low-frequency check (issuing N simultaneous session queries against a live source is
# a heavier footprint than ordinary collection), enforced here so a misconfiguration
# cannot silently turn it into a high-frequency scrape. Raise this only with a
# corresponding review of the source's rate limits in config/sources.yaml.
_MAX_RUNS_PER_DAY_CEILING = 6


class CookieState(StrEnum):
    """Session cookie posture varied across probe profiles."""

    NONE = "none"
    EXISTING_THIN = "existing_thin"  # one prior fixture/search hit
    EXISTING_THICK = "existing_thick"  # several prior hits


class PersonalisationProbeConfig(BaseModel):
    """N session profiles, issuing the identical query near-simultaneously.

    ``geographies`` is documented, not simulated with real network egress: phase 1
    varies only request headers (e.g. Accept-Language), consistent with
    ``apix_collector``'s own documented scope of not proxying real geo-IP traffic. See
    docs/personalisation-probe.md for the full method and its limitations.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    n_sessions: int = Field(ge=2, le=12)
    cookie_states: list[CookieState] = Field(min_length=1)
    ua_classes: list[str] = Field(min_length=1)
    geographies: list[str] = Field(min_length=1)
    routes: list[str] = Field(min_length=1)
    max_runs_per_day: int = Field(ge=1, le=_MAX_RUNS_PER_DAY_CEILING)
    min_interval_hours: float = Field(ge=1.0)

    @model_validator(mode="after")
    def _coherent(self) -> PersonalisationProbeConfig:
        n_profile_axes = len(self.cookie_states) * len(self.ua_classes) * len(self.geographies)
        if self.n_sessions > n_profile_axes:
            raise ValueError(
                f"n_sessions ({self.n_sessions}) exceeds the number of distinct "
                f"cookie_state x ua_class x geography combinations ({n_profile_axes})"
            )
        # A day has 24 hours; max_runs_per_day probe runs spaced at least
        # min_interval_hours apart must actually fit in a day, or the config is
        # internally inconsistent about what "low frequency" means.
        if self.max_runs_per_day * self.min_interval_hours > 24.0:
            raise ValueError(
                f"max_runs_per_day ({self.max_runs_per_day}) x min_interval_hours "
                f"({self.min_interval_hours}) exceeds 24 hours — inconsistent schedule"
            )
        return self


class SurgeConfig(BaseModel):
    """Flag a (route, date) cell beyond a band relative to its own seasonal baseline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    baseline_window_days: int = Field(ge=14, le=365)
    # Multiplier on the median-absolute-deviation band around the trailing baseline.
    band_width_k: float = Field(gt=0.0)
    min_history_periods: int = Field(ge=5)


class SellOutConfig(BaseModel):
    """Sell-out velocity: how quickly availability disappears per route."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lookback_days: int = Field(ge=7, le=365)
    min_group_size: int = Field(ge=1)


class RailConfig(BaseModel):
    """AC-2 rail-fare substitution comparison.

    ``corridor_map`` keys are basket route codes; values are the rail corridor
    identifier a :class:`apix_core.watchdog.rail.RailFareSource` would resolve. Empty
    is valid — no real rail-fare source exists yet
    (see docs/data-sources.md), and :class:`NotImplementedRailFareSource` is what runs
    until one is wired up.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    corridor_map: dict[str, str] = Field(default_factory=dict)


class WatchdogConfigFile(BaseModel):
    """The whole ``config/watchdog.yaml`` file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1, max_length=32)
    description: str = ""

    personalisation_probe: PersonalisationProbeConfig
    surge: SurgeConfig
    sellout: SellOutConfig
    rail: RailConfig


__all__ = [
    "CookieState",
    "PersonalisationProbeConfig",
    "RailConfig",
    "SellOutConfig",
    "SurgeConfig",
    "WatchdogConfigFile",
]
