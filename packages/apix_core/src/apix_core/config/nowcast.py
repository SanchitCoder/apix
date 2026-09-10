"""Schema for ``config/nowcast.yaml`` — the CPI bridge model, ATF pass-through and
movement-decomposition parameters.

Distinct from ``config/method.yaml``: that file governs how the index itself is
computed from cleaned quotes; this file governs how already-published APIx values are
used to *nowcast* the official CPI air-fare item index, estimate ATF pass-through, and
decompose a period's movement. Nothing here can change a published ``index_value`` —
only ``nowcast_value`` rows, which are never mistakable for the real index
(see ``apix_core.models.nowcast``).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BridgeModelKind(StrEnum):
    """The bridge-model family used to nowcast the CPI air-fare item index.

    ``OLS_LAGGED`` is the phase-1 default: a simple aggregated-regressor OLS with
    lags, chosen over MIDAS because true mixed-frequency estimation needs scaffolding
    this repo does not have yet (see docs/adr/0004-ols-lagged-bridge-over-midas.md).
    ``MIDAS`` is listed to state the growth path; selecting it is accepted by this
    schema but :func:`apix_core.nowcast.bridge.fit_bridge_model` raises
    ``NotImplementedError`` rather than silently falling back to OLS.
    """

    OLS_LAGGED = "ols_lagged"
    MIDAS = "midas"


class RobustCovType(StrEnum):
    """Covariance estimator for the bridge model's reported standard errors."""

    HAC = "HAC"  # Newey-West — appropriate for serially correlated monthly residuals
    HC1 = "HC1"  # heteroskedasticity-robust, no autocorrelation correction


class BridgeModelConfig(BaseModel):
    """Specification for the daily-APIx -> CPI air-fare bridge regression."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: BridgeModelKind = BridgeModelKind.OLS_LAGGED
    n_apix_lags: int = Field(ge=0, le=6)
    n_cpi_lags: int = Field(ge=0, le=6)
    # Below this many usable observations, fit_bridge_model refuses to fit rather than
    # return a point estimate nobody could trust — same refusal pattern as
    # apix_core.index.hedonic's min_r_squared floor.
    min_observations: int = Field(ge=8)
    ci_level: float = Field(default=0.95, gt=0.0, lt=1.0)
    robust_cov: RobustCovType = RobustCovType.HAC
    # Newey-West truncation lag when robust_cov is HAC. Ignored for HC1.
    hac_maxlags: int = Field(default=3, ge=1, le=12)

    @model_validator(mode="after")
    def _enough_observations_for_the_regressors(self) -> BridgeModelConfig:
        n_regressors = self.n_apix_lags + self.n_cpi_lags + 1  # +1: current APIx term
        min_needed = n_regressors + 3  # leave real degrees of freedom for inference
        if self.min_observations < min_needed:
            raise ValueError(
                f"min_observations ({self.min_observations}) must be at least "
                f"{min_needed} to leave residual degrees of freedom for "
                f"n_apix_lags={self.n_apix_lags}, n_cpi_lags={self.n_cpi_lags}"
            )
        return self


class AtfPassThroughConfig(BaseModel):
    """Distributed-lag specification for the ATF-price -> fare pass-through estimate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_lag: int = Field(ge=1, le=12)
    min_observations: int = Field(ge=8)

    @model_validator(mode="after")
    def _enough_observations_for_the_lags(self) -> AtfPassThroughConfig:
        min_needed = self.max_lag + 1 + 3
        if self.min_observations < min_needed:
            raise ValueError(
                f"min_observations ({self.min_observations}) must be at least "
                f"{min_needed} to leave residual degrees of freedom for max_lag="
                f"{self.max_lag}"
            )
        return self


class MovementDecompositionConfig(BaseModel):
    """Tolerance for the sum-to-total-change identity.

    Named distinctly from ``apix_core.config.cleaning.DecompositionConfig`` — that one
    governs splitting a raw fare into base/taxes/UDF/fee; this one governs decomposing
    an index *movement* into pure-price / mix / tax effects. Different concepts, same
    word in English, different config sections.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sum_tolerance: float = Field(default=1e-9, gt=0.0, le=1e-3)


class NowcastConfigFile(BaseModel):
    """The whole ``config/nowcast.yaml`` file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1, max_length=32)
    description: str = ""

    bridge_model: BridgeModelConfig
    atf_passthrough: AtfPassThroughConfig
    movement_decomposition: MovementDecompositionConfig


__all__ = [
    "AtfPassThroughConfig",
    "BridgeModelConfig",
    "BridgeModelKind",
    "MovementDecompositionConfig",
    "NowcastConfigFile",
    "RobustCovType",
]
