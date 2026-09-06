"""The loader fails loudly. A bad config file is never a partially-valid object."""

from __future__ import annotations

from pathlib import Path

import pytest

from apix_core.config import BasketConfig, ConfigError, load_basket, load_config, read_yaml
from apix_core.config.loader import CONFIG_DIR_ENV, find_config_dir


def test_missing_file_raises_config_error(tmp_config_dir: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_basket(tmp_config_dir)


def test_invalid_yaml_raises_config_error(tmp_config_dir: Path) -> None:
    (tmp_config_dir / "basket.yaml").write_text("routes: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_basket(tmp_config_dir)


def test_non_mapping_top_level_raises_config_error(tmp_config_dir: Path) -> None:
    (tmp_config_dir / "basket.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="expected a YAML mapping"):
        load_basket(tmp_config_dir)


def test_schema_violation_names_the_file_and_the_model(tmp_config_dir: Path) -> None:
    path = tmp_config_dir / "basket.yaml"
    path.write_text("basket_version: x\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="does not satisfy BasketConfig"):
        load_config(path, BasketConfig)


def test_read_yaml_returns_the_mapping(tmp_path: Path) -> None:
    path = tmp_path / "x.yaml"
    path.write_text("a: 1\nb: two\n", encoding="utf-8")
    assert read_yaml(path) == {"a": 1, "b": "two"}


def test_config_dir_is_discovered_from_the_checkout() -> None:
    """In a repo checkout the loader finds config/ by walking up from its own file."""
    found = find_config_dir()
    assert found.is_dir()
    assert (found / "basket.yaml").is_file()


def test_config_dir_env_var_wins(monkeypatch, tmp_path: Path) -> None:
    """The images set APIX_CONFIG_DIR, because in a wheel install the walk-up would
    land in site-packages rather than at /app/config."""
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path / "elsewhere"))
    assert find_config_dir() == tmp_path / "elsewhere"


def test_missing_config_dir_names_a_real_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    with pytest.raises(ConfigError, match=str(tmp_path)):
        load_basket()
