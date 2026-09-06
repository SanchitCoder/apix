"""Nowcast output.

Kept in its own table, never mixed into ``index_value``: a modelled estimate of a period
that is not yet closed must never be mistakable for a published index number.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from apix_core.models.base import Base, IndexNumber, created_at_col, uuid_pk


class NowcastValue(Base):
    """A point estimate with an interval, for a target series and period."""

    __tablename__ = "nowcast_value"

    id: Mapped[uuid.UUID] = uuid_pk()
    target_series: Mapped[str] = mapped_column(String(64), nullable=False)
    target_period: Mapped[date] = mapped_column(Date, nullable=False)
    point_estimate: Mapped[Decimal] = mapped_column(IndexNumber, nullable=False)
    ci_low: Mapped[Decimal | None] = mapped_column(IndexNumber)
    ci_high: Mapped[Decimal | None] = mapped_column(IndexNumber)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    produced_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        CheckConstraint(
            "ci_low IS NULL OR ci_high IS NULL OR ci_low <= ci_high", name="ci_ordered"
        ),
        Index("ix_nowcast_value_target", "target_series", "target_period"),
        Index("ix_nowcast_value_produced_at", "produced_at"),
    )
