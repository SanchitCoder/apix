"""Validated configuration for APIx.

Seven files, seven schemas, seven loaders. Each loader validates on read and raises
:class:`ConfigError` rather than returning a partially-valid object.
"""

from __future__ import annotations

from pathlib import Path

from apix_core.config.access import AccessConfig, RoleLimit
from apix_core.config.backtest import BacktestConfigFile
from apix_core.config.basket import AdvanceWindow, BasketConfig, RouteEntry
from apix_core.config.cleaning import (
    CleaningConfig,
    DecompositionConfig,
    DedupConfig,
    DistanceBand,
    ImputationConfig,
    OutlierConfig,
    OutlierRuleName,
    QualityGateConfig,
)
from apix_core.config.loader import (
    CONFIG_DIR_ENV,
    ConfigError,
    config_hash,
    find_config_dir,
    load_config,
    read_yaml,
)
from apix_core.config.method import (
    BookingProfile,
    ElementaryFormula,
    ImputationRule,
    MethodConfigFile,
    MultilateralMethod,
    OutlierRule,
    QualityAdjustment,
    SpliceMethod,
    WindowConfig,
)
from apix_core.config.nowcast import (
    AtfPassThroughConfig,
    BridgeModelConfig,
    BridgeModelKind,
    MovementDecompositionConfig,
    NowcastConfigFile,
    RobustCovType,
)
from apix_core.config.sources import SourceEntry, SourcePolicyConfig, SourcesConfig
from apix_core.config.synthetic import (
    AnomalyKind,
    AnomalySpec,
    BucketConfig,
    CarrierParams,
    CollectionShape,
    Festival,
    LeadTimeKnot,
    PricingConfig,
    SyntheticConfig,
    SyntheticSource,
)
from apix_core.config.watchdog import (
    CookieState,
    PersonalisationProbeConfig,
    RailConfig,
    SellOutConfig,
    SurgeConfig,
    WatchdogConfigFile,
)


def load_access(config_dir: Path | None = None) -> AccessConfig:
    """Load and validate ``config/access.yaml``."""
    return load_config((config_dir or find_config_dir()) / "access.yaml", AccessConfig)


def load_basket(config_dir: Path | None = None) -> BasketConfig:
    """Load and validate ``config/basket.yaml``."""
    return load_config((config_dir or find_config_dir()) / "basket.yaml", BasketConfig)


def load_cleaning(config_dir: Path | None = None) -> CleaningConfig:
    """Load and validate ``config/cleaning.yaml``."""
    return load_config((config_dir or find_config_dir()) / "cleaning.yaml", CleaningConfig)


def load_sources(config_dir: Path | None = None) -> SourcesConfig:
    """Load and validate ``config/sources.yaml``."""
    return load_config((config_dir or find_config_dir()) / "sources.yaml", SourcesConfig)


def load_method(config_dir: Path | None = None) -> MethodConfigFile:
    """Load and validate ``config/method.yaml``."""
    return load_config((config_dir or find_config_dir()) / "method.yaml", MethodConfigFile)


def load_synthetic(config_dir: Path | None = None) -> SyntheticConfig:
    """Load and validate ``config/synthetic.yaml``."""
    return load_config((config_dir or find_config_dir()) / "synthetic.yaml", SyntheticConfig)


def load_nowcast(config_dir: Path | None = None) -> NowcastConfigFile:
    """Load and validate ``config/nowcast.yaml``."""
    return load_config((config_dir or find_config_dir()) / "nowcast.yaml", NowcastConfigFile)


def load_watchdog(config_dir: Path | None = None) -> WatchdogConfigFile:
    """Load and validate ``config/watchdog.yaml``."""
    return load_config((config_dir or find_config_dir()) / "watchdog.yaml", WatchdogConfigFile)


def load_backtest(config_dir: Path | None = None) -> BacktestConfigFile:
    """Load and validate ``config/backtest.yaml``."""
    return load_config((config_dir or find_config_dir()) / "backtest.yaml", BacktestConfigFile)


__all__ = [
    "CONFIG_DIR_ENV",
    "AccessConfig",
    "AdvanceWindow",
    "AnomalyKind",
    "AnomalySpec",
    "AtfPassThroughConfig",
    "BacktestConfigFile",
    "BasketConfig",
    "BookingProfile",
    "BridgeModelConfig",
    "BridgeModelKind",
    "BucketConfig",
    "CarrierParams",
    "CleaningConfig",
    "CollectionShape",
    "ConfigError",
    "CookieState",
    "DecompositionConfig",
    "DedupConfig",
    "DistanceBand",
    "ElementaryFormula",
    "Festival",
    "ImputationConfig",
    "ImputationRule",
    "LeadTimeKnot",
    "MethodConfigFile",
    "MovementDecompositionConfig",
    "MultilateralMethod",
    "OutlierConfig",
    "OutlierRule",
    "OutlierRuleName",
    "PersonalisationProbeConfig",
    "PricingConfig",
    "QualityAdjustment",
    "QualityGateConfig",
    "RailConfig",
    "RobustCovType",
    "RoleLimit",
    "RouteEntry",
    "SellOutConfig",
    "SourceEntry",
    "SourcePolicyConfig",
    "SourcesConfig",
    "SpliceMethod",
    "SurgeConfig",
    "SyntheticConfig",
    "SyntheticSource",
    "WatchdogConfigFile",
    "WindowConfig",
    "config_hash",
    "find_config_dir",
    "load_access",
    "load_backtest",
    "load_basket",
    "load_cleaning",
    "load_config",
    "load_method",
    "load_nowcast",
    "load_sources",
    "load_synthetic",
    "load_watchdog",
    "read_yaml",
]
