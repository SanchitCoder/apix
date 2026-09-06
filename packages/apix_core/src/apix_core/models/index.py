"""Index production tables.

The reproducibility contract lives here. An ``index_run`` is stamped with exactly two
things: the ``data_snapshot`` it consumed and the ``method_config`` it applied. Re-running
the same pair must produce byte-identical output — principle 4 in CLAUDE.md.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apix_core.models.base import Base, IndexNumber, created_at_col, pg_enum, uuid_pk
from apix_core.models.enums import Frequency, RunStatus


class DataSnapshot(Base):
    """A frozen, hashed view of the cleaned input data.

    ``content_hash`` is computed over the canonical serialisation of the rows in the
    snapshot. Two snapshots with the same hash are the same data.
    """

    __tablename__ = "data_snapshot"

    id: Mapped[uuid.UUID] = uuid_pk()
    created_at: Mapped[datetime] = created_at_col()
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("row_count >= 0", name="row_count_non_negative"),
        Index("ix_data_snapshot_content_hash", "content_hash"),
        Index("ix_data_snapshot_created_at", "created_at"),
    )


class MethodConfig(Base):
    """A versioned, hashed copy of the method configuration actually used.

    The YAML under ``config/method.yaml`` is the editable source; this table is the
    immutable record of what a given run applied. ``config_hash`` is unique, so an
    unchanged method reuses its row.
    """

    __tablename__ = "method_config"

    id: Mapped[uuid.UUID] = uuid_pk()
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class IndexRun(Base):
    """One computation of the index."""

    __tablename__ = "index_run"

    id: Mapped[uuid.UUID] = uuid_pk()
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_snapshot.id", ondelete="RESTRICT"), nullable=False
    )
    method_config_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("method_config.id", ondelete="RESTRICT"), nullable=False
    )
    # The date the published figures are "as of". Vintages are how revisions are
    # served: /v1/index/vintage asks for a period as it stood on a given date.
    vintage_date: Mapped[date] = mapped_column(Date, nullable=False)
    computed_at: Mapped[datetime] = created_at_col()
    status: Mapped[RunStatus] = mapped_column(
        pg_enum(RunStatus, "run_status_enum"), nullable=False, server_default=text("'PENDING'")
    )

    __table_args__ = (
        Index("ix_index_run_vintage_date", "vintage_date"),
        Index("ix_index_run_snapshot_method", "snapshot_id", "method_config_id"),
    )


class Series(Base):
    """A published statistical series.

    ``dimensions`` holds the SDMX key components (route, carrier type, advance-purchase
    window, ...) as a JSON object, so new breakdowns do not require a migration.
    """

    __tablename__ = "series"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    dimensions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    frequency: Mapped[Frequency] = mapped_column(
        pg_enum(Frequency, "frequency_enum"), nullable=False
    )

    __table_args__ = (Index("ix_series_dimensions", "dimensions", postgresql_using="gin"),)


class IndexValue(Base):
    """One index number, for one series, in one period, from one run.

    The primary key is (run, series, period): the same period computed by a later run is
    a new row, not an overwrite. That is what makes vintages possible and revisions
    visible.

    ``n_quotes`` and ``coverage_pct`` travel with the value because a national
    statistics office will not publish a number without knowing what it rests on.
    """

    __tablename__ = "index_value"

    index_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("index_run.id", ondelete="CASCADE"), primary_key=True
    )
    series_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("series.id", ondelete="RESTRICT"), primary_key=True
    )
    period: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[Decimal] = mapped_column(IndexNumber, nullable=False)
    n_quotes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    coverage_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    __table_args__ = (
        CheckConstraint("n_quotes >= 0", name="n_quotes_non_negative"),
        CheckConstraint(
            "coverage_pct IS NULL OR (coverage_pct >= 0 AND coverage_pct <= 100)",
            name="coverage_pct_range",
        ),
        # The dashboard reads a series across time; this is its hot path.
        Index("ix_index_value_series_period", "series_id", "period"),
        Index("ix_index_value_run", "index_run_id"),
    )


class RevisionLog(Base):
    """Every change to an already-published number, with a reason.

    A revision that is not in this table did not happen. ``old_value`` is NULL for a
    first publication of a period.
    """

    __tablename__ = "revision_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    series_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("series.id", ondelete="RESTRICT"), nullable=False
    )
    period: Mapped[date] = mapped_column(Date, nullable=False)
    old_value: Mapped[Decimal | None] = mapped_column(IndexNumber)
    new_value: Mapped[Decimal] = mapped_column(IndexNumber, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    revised_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("series_id", "period", "revised_at", name="uq_revision_log_event"),
        Index("ix_revision_log_series_period", "series_id", "period"),
    )
