"""resolve(): the full chain, or a loud ProvenanceError — never a partial answer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apix_core.models.collection import CollectionRun, PolicyDecision, Source
from apix_core.models.enums import (
    CollectionMethod,
    LegalBasis,
    PolicyDecisionOutcome,
    RunStatus,
    SourceType,
)
from apix_core.models.quotes import FareQuote
from apix_core.provenance import ProvenanceError, resolve

COLLECTED_AT = datetime(2026, 9, 4, 9, 30, tzinfo=UTC)
URL_HASH = "ab" * 32


def build_chain():
    source_id = uuid.uuid4()
    run_id = uuid.uuid4()
    quote = FareQuote(
        id=uuid.uuid4(),
        collected_at=COLLECTED_AT,
        run_id=run_id,
        source_id=source_id,
        collection_method=CollectionMethod.FIXTURE,
        legal_basis=LegalBasis.FIXTURE,
        source_url_hash=URL_HASH,
        content_hash="cd" * 32,
        raw_payload_ref="sha256/cd/cd/" + "cd" * 32,
        total_fare=Decimal("4999.00"),
    )
    run = CollectionRun(
        id=run_id,
        source_id=source_id,
        started_at=COLLECTED_AT - timedelta(minutes=2),
        finished_at=COLLECTED_AT + timedelta(minutes=1),
        status=RunStatus.SUCCEEDED,
        quotes_collected=12,
        blocked_count=0,
        error_class=None,
    )
    source = Source(
        id=source_id,
        code="fixture_replay",
        display_name="Recorded fixture replay",
        domain="localhost",
        source_type=SourceType.OFFICIAL,
        enabled=True,
    )
    decision = PolicyDecision(
        id=uuid.uuid4(),
        source_id=source_id,
        url_hash=URL_HASH,
        decision=PolicyDecisionOutcome.ALLOWED,
        reason="all checks passed",
        decided_at=COLLECTED_AT - timedelta(seconds=1),
    )
    return quote, run, source, decision


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    """Duck-typed Session: routes each query by the entity it selects."""

    def __init__(self, quote=None, run=None, source=None, decision=None):
        self.quote = quote
        self.run = run
        self.source = source
        self.decision = decision

    def execute(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is FareQuote:
            return FakeResult(self.quote)
        if entity is PolicyDecision:
            return FakeResult(self.decision)
        raise AssertionError(f"unexpected query for {entity}")

    def get(self, model, pk):
        if model is CollectionRun:
            return self.run if self.run is not None and self.run.id == pk else None
        if model is Source:
            return self.source if self.source is not None and self.source.id == pk else None
        raise AssertionError(f"unexpected get for {model}")


def test_resolve_returns_the_full_chain():
    quote, run, source, decision = build_chain()
    session = FakeSession(quote=quote, run=run, source=source, decision=decision)

    chain = resolve(session, quote.id)

    assert chain.quote.id == quote.id
    assert chain.quote.content_hash == quote.content_hash
    assert chain.quote.legal_basis is LegalBasis.FIXTURE
    assert chain.run.id == run.id
    assert chain.run.status is RunStatus.SUCCEEDED
    assert chain.source.code == "fixture_replay"
    assert chain.policy_decision is not None
    assert chain.policy_decision.decision is PolicyDecisionOutcome.ALLOWED
    assert chain.raw_payload_ref == quote.raw_payload_ref


def test_resolve_serialises_cleanly():
    """The chain backs /v1/provenance, so it must dump to JSON-safe primitives."""
    quote, run, source, decision = build_chain()
    session = FakeSession(quote=quote, run=run, source=source, decision=decision)
    payload = resolve(session, quote.id).model_dump(mode="json")
    assert payload["quote"]["id"] == str(quote.id)
    assert payload["source"]["source_type"] == "OFFICIAL"
    assert payload["policy_decision"]["decision"] == "ALLOWED"


def test_missing_quote_raises():
    session = FakeSession()
    with pytest.raises(ProvenanceError, match="no fare_quote"):
        resolve(session, uuid.uuid4())


def test_missing_run_is_corruption_not_a_gap():
    quote, _, source, decision = build_chain()
    session = FakeSession(quote=quote, run=None, source=source, decision=decision)
    with pytest.raises(ProvenanceError, match="missing collection_run"):
        resolve(session, quote.id)


def test_missing_source_is_corruption_not_a_gap():
    quote, run, _, decision = build_chain()
    session = FakeSession(quote=quote, run=run, source=None, decision=decision)
    with pytest.raises(ProvenanceError, match="missing source"):
        resolve(session, quote.id)


def test_chain_without_a_recorded_decision_is_explicit_about_it():
    """FIXTURE replays outside a live engine have no decision row; the chain says so
    with an explicit None rather than omitting the field."""
    quote, run, source, _ = build_chain()
    session = FakeSession(quote=quote, run=run, source=source, decision=None)
    chain = resolve(session, quote.id)
    assert chain.policy_decision is None
