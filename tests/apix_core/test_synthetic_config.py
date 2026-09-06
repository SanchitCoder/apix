"""Schema validation for config/synthetic.yaml — the labelled scenario parameters."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apix_core.config import load_synthetic
from apix_core.config.synthetic import (
    BucketConfig,
    CollectionShape,
    SyntheticConfig,
    SyntheticSource,
)


def test_the_shipped_synthetic_config_is_valid(config_dir) -> None:
    cfg = load_synthetic(config_dir)
    assert cfg.seed == 20260904
    assert all(s.code.startswith("synthetic_") for s in cfg.sources)


def test_source_codes_must_carry_the_synthetic_prefix() -> None:
    """The label is what keeps generated rows unmistakable; the schema enforces it."""
    with pytest.raises(ValidationError, match="synthetic_"):
        SyntheticSource(code="ota_lookalike", display_name="nope", convenience_fee_inr=0)


def test_bucket_ladder_must_close_cheap_buckets_first() -> None:
    with pytest.raises(ValidationError, match="non-increasing"):
        BucketConfig(
            count=3,
            price_step=0.1,
            close_days_mu=[5.0, 10.0, 0.0],
            close_days_sigma=1.0,
            demand_sensitivity=0.5,
        )


def test_bucket_ladder_length_must_match_count() -> None:
    with pytest.raises(ValidationError, match="exactly"):
        BucketConfig(
            count=4,
            price_step=0.1,
            close_days_mu=[10.0, 5.0, 0.0],
            close_days_sigma=1.0,
            demand_sensitivity=0.5,
        )


def test_lead_time_knots_must_be_strictly_decreasing(config_dir) -> None:
    cfg = load_synthetic(config_dir)
    with pytest.raises(ValidationError, match="strictly decreasing"):
        SyntheticConfig.model_validate(
            {
                **cfg.model_dump(),
                "lead_time_knots": [
                    {"days_before_departure": 10, "multiplier": 1.0},
                    {"days_before_departure": 10, "multiplier": 1.2},
                ],
            }
        )


def test_dow_multipliers_need_all_seven_days(config_dir) -> None:
    cfg = load_synthetic(config_dir)
    dows = dict(cfg.dow_multipliers)
    dows.pop("fri")
    with pytest.raises(ValidationError, match="exactly the keys"):
        SyntheticConfig.model_validate({**cfg.model_dump(), "dow_multipliers": dows})


def test_advance_grid_must_be_increasing() -> None:
    with pytest.raises(ValidationError, match="strictly increasing"):
        CollectionShape(
            advance_days_grid=[7, 3, 14],
            flights_per_route_carrier=1,
            carriers_per_route_min=1,
            carriers_per_route_max=1,
            collection_hour_ist=6,
        )


def test_one_anomaly_spec_per_kind(config_dir) -> None:
    cfg = load_synthetic(config_dir)
    doubled = [a.model_dump() for a in cfg.anomalies] + [cfg.anomalies[0].model_dump()]
    with pytest.raises(ValidationError, match="one AnomalySpec per kind"):
        SyntheticConfig.model_validate({**cfg.model_dump(), "anomalies": doubled})
