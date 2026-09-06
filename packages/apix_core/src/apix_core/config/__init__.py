"""Validated configuration for APIx.

Four files, four schemas, four loaders. Each loader validates on read and raises
:class:`ConfigError` rather than returning a partially-valid object.
"""

from __future__ import annotations

from pathlib import Path

from apix_core.config.basket import AdvanceWindow, BasketConfig, RouteEntry
from apix_core.config.loader import (
    CONFIG_DIR_ENV,
    ConfigError,
    config_hash,
    find_config_dir,
    load_config,
    read_yaml,
)
from apix_core.config.method import (
    ElementaryFormula,
    ImputationRule,
    MethodConfigFile,
    MultilateralMethod,
    OutlierRule,
    QualityAdjustment,
    SpliceMethod,
    WindowConfig,
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


def load_basket(config_dir: Path | None = None) -> BasketConfig:
    """Load and validate ``config/basket.yaml``."""
    return load_config((config_dir or find_config_dir()) / "basket.yaml", BasketConfig)


def load_sources(config_dir: Path | None = None) -> SourcesConfig:
    """Load and validate ``config/sources.yaml``."""
    return load_config((config_dir or find_config_dir()) / "sources.yaml", SourcesConfig)


def load_method(config_dir: Path | None = None) -> MethodConfigFile:
    """Load and validate ``config/method.yaml``."""
    return load_config((config_dir or find_config_dir()) / "method.yaml", MethodConfigFile)


def load_synthetic(config_dir: Path | None = None) -> SyntheticConfig:
    """Load and validate ``config/synthetic.yaml``."""
    return load_config((config_dir or find_config_dir()) / "synthetic.yaml", SyntheticConfig)


__all__ = [
    "CONFIG_DIR_ENV",
    "AdvanceWindow",
    "AnomalyKind",
    "AnomalySpec",
    "BasketConfig",
    "BucketConfig",
    "CarrierParams",
    "CollectionShape",
    "ConfigError",
    "ElementaryFormula",
    "Festival",
    "ImputationRule",
    "LeadTimeKnot",
    "MethodConfigFile",
    "MultilateralMethod",
    "OutlierRule",
    "PricingConfig",
    "QualityAdjustment",
    "RouteEntry",
    "SourceEntry",
    "SourcePolicyConfig",
    "SourcesConfig",
    "SpliceMethod",
    "SyntheticConfig",
    "SyntheticSource",
    "WindowConfig",
    "config_hash",
    "find_config_dir",
    "load_basket",
    "load_config",
    "load_method",
    "load_sources",
    "load_synthetic",
    "read_yaml",
]
