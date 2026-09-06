"""``source``/``source_policy`` row-shaping from ``config/sources.yaml``."""

from __future__ import annotations

from apix_core.config import load_sources
from apix_core.seeding.sources import source_policy_rows, source_rows


def test_source_rows_cover_every_configured_source(config_dir) -> None:
    config = load_sources(config_dir)
    rows = source_rows(config)
    assert {r["code"] for r in rows} == {s.code for s in config.sources}
    fixture_row = next(r for r in rows if r["code"] == "fixture_replay")
    assert fixture_row["enabled"] is True
    assert fixture_row["domain"] == "localhost"


def test_only_fixture_replay_is_enabled_today(config_dir) -> None:
    """A guardrail on the shipped config, not just the code: every real source must
    still be disabled pending legal review (CLAUDE.md guardrail 3)."""
    config = load_sources(config_dir)
    rows = source_rows(config)
    enabled = {r["code"] for r in rows if r["enabled"]}
    assert enabled == {"fixture_replay"}


def test_source_policy_rows_reference_the_right_source_id(config_dir) -> None:
    config = load_sources(config_dir)
    fake_ids = {s.code: f"id-{s.code}" for s in config.sources}
    rows = source_policy_rows(config, fake_ids)
    by_source = {r["source_id"]: r for r in rows}
    for source in config.sources:
        row = by_source[fake_ids[source.code]]
        assert row["tos_verdict"] == source.policy.tos_verdict.value
        assert row["crawl_delay_s"] == source.policy.crawl_delay_s
        assert row["max_requests_per_hour"] == source.policy.max_requests_per_hour
