"""Resolving the full provenance chain for one quote.

``resolve(session, quote_id)`` walks quote -> run -> source -> policy decision -> raw
payload reference and returns the whole chain as one serialisable record. This backs
the ``/v1/provenance`` endpoint. A quote whose chain cannot be completed is a
:class:`ProvenanceError`, never a partial answer presented as a whole one.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from apix_core.models.collection import CollectionRun, PolicyDecision, Source
from apix_core.models.enums import (
    CollectionMethod,
    LegalBasis,
    PolicyDecisionOutcome,
    RunStatus,
    SourceType,
)
from apix_core.models.quotes import FareQuote
from apix_core.provenance.store import ProvenanceError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class _FromOrm(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)


class QuoteProvenance(_FromOrm):
    """The quote itself: what was observed, when, and its evidence hashes."""

    id: uuid.UUID
    collected_at: datetime
    run_id: uuid.UUID
    source_id: uuid.UUID
    collection_method: CollectionMethod
    legal_basis: LegalBasis
    source_url_hash: str
    content_hash: str
    raw_payload_ref: str | None


class RunProvenance(_FromOrm):
    """The collection run that produced the quote."""

    id: uuid.UUID
    started_at: datetime
    finished_at: datetime | None
    status: RunStatus
    quotes_collected: int
    blocked_count: int
    error_class: str | None


class SourceProvenance(_FromOrm):
    """Where the quote came from."""

    id: uuid.UUID
    code: str
    display_name: str
    domain: str
    source_type: SourceType
    enabled: bool


class DecisionProvenance(_FromOrm):
    """The recorded PolicyEngine decision that authorised the fetch."""

    id: uuid.UUID
    url_hash: str
    decision: PolicyDecisionOutcome
    reason: str
    decided_at: datetime


class ProvenanceChain(BaseModel):
    """One quote, fully accounted for."""

    model_config = ConfigDict(frozen=True)

    quote: QuoteProvenance
    run: RunProvenance
    source: SourceProvenance
    # None only for FIXTURE-legal-basis quotes replayed outside a live engine; a live
    # collection always has its authorising decision on record.
    policy_decision: DecisionProvenance | None
    raw_payload_ref: str | None


def resolve(session: Session, quote_id: uuid.UUID) -> ProvenanceChain:
    """Walk the full chain for ``quote_id``.

    Raises :class:`ProvenanceError` if the quote does not exist or if any link that
    the schema guarantees (run, source) is missing — a broken chain is corruption to
    surface, not a gap to paper over.
    """
    quote = session.execute(select(FareQuote).where(FareQuote.id == quote_id)).scalar_one_or_none()
    if quote is None:
        raise ProvenanceError(f"no fare_quote with id {quote_id}")

    run = session.get(CollectionRun, quote.run_id)
    if run is None:
        raise ProvenanceError(f"quote {quote_id} references missing collection_run {quote.run_id}")
    source = session.get(Source, quote.source_id)
    if source is None:
        raise ProvenanceError(f"quote {quote_id} references missing source {quote.source_id}")

    # The decision that authorised this fetch: same source, same normalised URL, the
    # most recent one at or before the moment of collection.
    decision = session.execute(
        select(PolicyDecision)
        .where(
            PolicyDecision.source_id == quote.source_id,
            PolicyDecision.url_hash == quote.source_url_hash,
            PolicyDecision.decided_at <= quote.collected_at,
        )
        .order_by(PolicyDecision.decided_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    return ProvenanceChain(
        quote=QuoteProvenance.model_validate(quote),
        run=RunProvenance.model_validate(run),
        source=SourceProvenance.model_validate(source),
        policy_decision=(
            DecisionProvenance.model_validate(decision) if decision is not None else None
        ),
        raw_payload_ref=quote.raw_payload_ref,
    )


__all__ = [
    "DecisionProvenance",
    "ProvenanceChain",
    "QuoteProvenance",
    "RunProvenance",
    "SourceProvenance",
    "resolve",
]
