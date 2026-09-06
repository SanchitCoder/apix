"""YAML config loading with schema validation and content hashing.

Config is versioned data, not code. Every file under ``config/`` has a Pydantic schema
here and is validated on load; an invalid file is a startup failure. The hash of the
canonical serialisation is what gets stamped onto an index run.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

CONFIG_DIR_ENV = "APIX_CONFIG_DIR"

# Marker file that identifies a real config directory.
_MARKER = Path("config") / "basket.yaml"


def find_config_dir() -> Path:
    """Locate the ``config/`` directory.

    Resolved rather than hard-coded because the package runs from two very different
    layouts: a repo checkout, where it sits under ``packages/apix_core/src``, and a
    container image, where it is an installed wheel in ``site-packages`` with the config
    mounted at ``/app/config``. A path computed from ``__file__`` alone is correct in the
    first and wrong in the second.

    Order of resolution:

    1. ``APIX_CONFIG_DIR``, if set. The images set it explicitly.
    2. The nearest ancestor of this file that contains ``config/basket.yaml``.
    3. The nearest ancestor of the working directory that contains it.

    Returns ``<cwd>/config`` if none matches, so the caller gets a "config file not
    found" naming a real path rather than a confusing one.
    """
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return Path(override)
    for start in (Path(__file__).resolve(), Path.cwd().resolve()):
        for parent in (start, *start.parents):
            if (parent / _MARKER).is_file():
                return parent / "config"
    return Path.cwd() / "config"


class ConfigError(RuntimeError):
    """Raised when a config file is missing, unparseable or fails its schema."""


def read_yaml(path: Path) -> dict[str, Any]:
    """Parse a YAML mapping from ``path``."""
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a YAML mapping at the top level")
    return raw


def load_config[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    """Load and validate one YAML file against ``model``."""
    data = read_yaml(path)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{path}: does not satisfy {model.__name__}:\n{exc}") from exc


def config_hash(model: BaseModel) -> str:
    """Stable SHA-256 over a validated config.

    Computed from the canonical JSON form (sorted keys, no whitespace) so that
    reformatting the YAML does not change the hash, but changing a value does.
    """
    payload = model.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "CONFIG_DIR_ENV",
    "ConfigError",
    "config_hash",
    "find_config_dir",
    "load_config",
    "read_yaml",
]
