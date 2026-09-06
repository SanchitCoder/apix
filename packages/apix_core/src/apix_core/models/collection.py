"""Collection-side tables: sources, their compliance policy, decisions and runs.

``source_policy`` is the machine-readable form of the compliance position for a source.
``policy_decision`` is the append-only audit trail proving that the PolicyEngine was
consulted before each request — principle 3 in CLAUDE.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apix_core.models.base import Base, created_at_col, pg_enum, uuid_pk
from apix_core.models.enums import PolicyDecisionOutcome, RunStatus, SourceType, TosVerdict


class Source(Base):
    """A site or feed we collect from."""

    __tablename__ = "source"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        pg_enum(SourceType, "source_type_enum"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    policy: Mapped[SourcePolicy | None] = relationship(
        back_populates="source", uselist=False, lazy="raise"
    )

    __table_args__ = (Index("ix_source_enabled", "enabled"),)


class SourcePolicy(Base):
    """The compliance policy for one source. One row per source.

    ``legal_basis`` records why collection is permitted. ``tos_verdict`` is the outcome
    of a human review — AMBIGUOUS is treated as prohibited until a human resolves it.
    ``robots_etag``/``robots_fetched_at`` let the engine revalidate robots.txt cheaply
    and prove which version of it a decision was made under.
    """

    __tablename__ = "source_policy"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source.id", ondelete="CASCADE"), primary_key=True
    )
    robots_url: Mapped[str | None] = mapped_column(String(512))
    allowed_paths: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    disallowed_paths: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    crawl_delay_s: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, server_default=text("2.0")
    )
    max_requests_per_hour: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("60")
    )
    tos_url: Mapped[str | None] = mapped_column(String(512))
    tos_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tos_verdict: Mapped[TosVerdict] = mapped_column(
        pg_enum(TosVerdict, "tos_verdict_enum"),
        nullable=False,
        server_default=text("'NOT_REVIEWED'"),
    )
    legal_basis: Mapped[str | None] = mapped_column(String(64))
    robots_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    robots_etag: Mapped[str | None] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    source: Mapped[Source] = relationship(back_populates="policy", lazy="raise")

    __table_args__ = (
        CheckConstraint("crawl_delay_s >= 0", name="crawl_delay_non_negative"),
        CheckConstraint("max_requests_per_hour > 0", name="rate_limit_positive"),
    )


class PolicyDecision(Base):
    """One recorded decision by the PolicyEngine. Append-only.

    ``url_hash`` rather than the URL itself: the decision trail must be auditable
    without storing query strings that may carry incidental personal data.
    """

    __tablename__ = "policy_decision"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source.id", ondelete="RESTRICT"), nullable=False
    )
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[PolicyDecisionOutcome] = mapped_column(
        pg_enum(PolicyDecisionOutcome, "policy_decision_outcome_enum"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        Index("ix_policy_decision_source_decided", "source_id", "decided_at"),
        Index("ix_policy_decision_url_hash", "url_hash"),
    )


class CollectionRun(Base):
    """One execution of one collector against one source (optionally one route).

    A run that collected nothing is still a row. ``blocked_count`` and ``error_class``
    make an empty result legible as data rather than as a gap — principle 2.
    """

    __tablename__ = "collection_run"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source.id", ondelete="RESTRICT"), nullable=False
    )
    route_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("route.id", ondelete="RESTRICT"))
    started_at: Mapped[datetime] = created_at_col()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[RunStatus] = mapped_column(
        pg_enum(RunStatus, "run_status_enum"), nullable=False, server_default=text("'PENDING'")
    )
    quotes_collected: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_class: Mapped[str | None] = mapped_column(String(128))
    error_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint("quotes_collected >= 0", name="quotes_non_negative"),
        CheckConstraint("blocked_count >= 0", name="blocked_non_negative"),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="finished_after_started"
        ),
        Index("ix_collection_run_source_started", "source_id", "started_at"),
        Index("ix_collection_run_route_started", "route_id", "started_at"),
        Index("ix_collection_run_status", "status"),
    )
