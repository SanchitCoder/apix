"""A source cannot be switched on without a reviewed, permissive legal basis."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from apix_core.config import SourceEntry, load_sources
from apix_core.models.enums import LegalBasis, SourceType, TosVerdict


def _entry(**overrides: object) -> dict[str, object]:
    policy: dict[str, object] = {
        "tos_url": "https://example.org/tos",
        "tos_reviewed_at": datetime(2026, 1, 5, tzinfo=UTC),
        "tos_verdict": TosVerdict.PERMITTED,
        "legal_basis": LegalBasis.TOS_PERMITTED,
    }
    policy.update(overrides.pop("policy", {}))  # type: ignore[arg-type]
    entry: dict[str, object] = {
        "code": "example_src",
        "display_name": "Example",
        "domain": "example.org",
        "source_type": SourceType.OTA,
        "enabled": True,
        "policy": policy,
    }
    entry.update(overrides)
    return entry


class TestShippedSources:
    def test_the_real_sources_file_validates(self, config_dir) -> None:
        sources = load_sources(config_dir)
        assert len(sources.sources) >= 1

    def test_only_the_offline_fixture_source_is_enabled(self, config_dir) -> None:
        """Nothing that makes a network request ships enabled.

        Every real site is disabled with tos_verdict NOT_REVIEWED. Turning one on is a
        deliberate act that requires recording a human review first.
        """
        sources = load_sources(config_dir)
        assert sources.enabled_codes == ["fixture_replay"]

    def test_no_real_domain_claims_a_review_that_has_not_happened(self, config_dir) -> None:
        for source in load_sources(config_dir).sources:
            if source.code == "fixture_replay":
                continue
            assert source.policy.tos_verdict is TosVerdict.NOT_REVIEWED
            assert source.policy.legal_basis is None


class TestSourceValidation:
    def test_enabled_source_needs_a_permitted_verdict(self) -> None:
        with pytest.raises(ValidationError, match="Only PERMITTED sources"):
            SourceEntry.model_validate(
                _entry(
                    policy={
                        "tos_verdict": TosVerdict.AMBIGUOUS,
                        "legal_basis": LegalBasis.TOS_PERMITTED,
                    }
                )
            )

    def test_ambiguous_is_treated_as_prohibited(self) -> None:
        """AMBIGUOUS must never behave like PERMITTED."""
        with pytest.raises(ValidationError):
            SourceEntry.model_validate(_entry(policy={"tos_verdict": TosVerdict.AMBIGUOUS}))

    def test_enabled_source_needs_a_legal_basis(self) -> None:
        with pytest.raises(ValidationError, match="no legal_basis"):
            SourceEntry.model_validate(_entry(policy={"legal_basis": None}))

    def test_reviewed_verdict_requires_evidence(self) -> None:
        with pytest.raises(ValidationError, match="requires tos_url"):
            SourceEntry.model_validate(_entry(policy={"tos_url": None}))
        with pytest.raises(ValidationError, match="requires tos_reviewed_at"):
            SourceEntry.model_validate(_entry(policy={"tos_reviewed_at": None}))

    def test_disabled_source_may_be_unreviewed(self) -> None:
        entry = SourceEntry.model_validate(
            _entry(
                enabled=False,
                policy={
                    "tos_url": None,
                    "tos_reviewed_at": None,
                    "tos_verdict": TosVerdict.NOT_REVIEWED,
                    "legal_basis": None,
                },
            )
        )
        assert entry.enabled is False

    def test_duplicate_source_codes_are_rejected(self) -> None:
        from apix_core.config import SourcesConfig

        with pytest.raises(ValidationError, match="duplicate source codes"):
            SourcesConfig.model_validate({"version": "t", "sources": [_entry(), _entry()]})
