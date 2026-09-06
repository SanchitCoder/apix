"""``fare_quote_clean`` — the analysis-ready table.

Every correction to the raw record happens here, never in ``fare_quote``. A cleaned row
either points back at the raw quote it derives from, or is explicitly flagged as
imputed with the rule that produced it. There is no third possibility: a row with
``quote_id IS NULL`` and ``is_imputed = false`` is rejected by a check constraint.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apix_core.models.base import Base, Money, created_at_col, uuid_pk


class FareQuoteClean(Base):
    """One normalised, quality-checked observation.

    ``quote_id`` plus ``quote_collected_at`` form a composite foreign key into
    ``fare_quote`` — the timestamp is carried because the raw table is a Timescale
    hypertable whose primary key includes its partition column. Both are NULL for a
    purely imputed row.
    """

    __tablename__ = "fare_quote_clean"

    id: Mapped[uuid.UUID] = uuid_pk()

    # --- lineage ---------------------------------------------------------------
    quote_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    quote_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The frozen input set this row belongs to. Reproducibility hangs off this.
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_snapshot.id", ondelete="RESTRICT"), nullable=False
    )

    # --- normalised dimensions -------------------------------------------------
    route_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("route.id", ondelete="RESTRICT"), nullable=False
    )
    carrier_iata: Mapped[str] = mapped_column(
        String(2), ForeignKey("carrier.iata", ondelete="RESTRICT"), nullable=False
    )
    travel_date: Mapped[date] = mapped_column(Date, nullable=False)
    advance_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Departure time bucket (0-23, local). Time-of-day is a price determinant and a
    # hedonic characteristic, so it is a first-class dimension.
    dep_hour_bucket: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    stops: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # --- values ----------------------------------------------------------------
    base_fare: Mapped[Decimal | None] = mapped_column(Money)
    total_fare: Mapped[Decimal] = mapped_column(Money, nullable=False)

    # --- treatment record ------------------------------------------------------
    is_outlier: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    outlier_rule: Mapped[str | None] = mapped_column(String(64))
    is_imputed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    imputation_method: Mapped[str | None] = mapped_column(String(64))
    # Per-row quality flags: completeness, source agreement, staleness and so on.
    # JSONB because the vector grows as new checks are added without a migration.
    quality_vector: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        ForeignKeyConstraint(
            ["quote_id", "quote_collected_at"],
            ["fare_quote.id", "fare_quote.collected_at"],
            name="fk_fare_quote_clean_quote",
            ondelete="RESTRICT",
        ),
        # Lineage is mandatory: derived from a raw quote, or explicitly imputed.
        CheckConstraint(
            "(quote_id IS NOT NULL AND quote_collected_at IS NOT NULL) OR is_imputed",
            name="lineage_or_imputed",
        ),
        # Nothing fails silently: a flag without its reason is not allowed.
        CheckConstraint("(NOT is_outlier) OR outlier_rule IS NOT NULL", name="outlier_needs_rule"),
        CheckConstraint(
            "(NOT is_imputed) OR imputation_method IS NOT NULL", name="imputed_needs_method"
        ),
        CheckConstraint("dep_hour_bucket BETWEEN 0 AND 23", name="dep_hour_bucket_range"),
        CheckConstraint("advance_days >= 0 AND advance_days <= 365", name="advance_days_range"),
        CheckConstraint("total_fare >= 0", name="total_fare_non_negative"),
        # Dashboard query patterns.
        Index("ix_fare_quote_clean_route_travel_date", "route_id", "travel_date"),
        Index(
            "ix_fare_quote_clean_route_advance_travel",
            "route_id",
            "advance_days",
            "travel_date",
        ),
        Index("ix_fare_quote_clean_snapshot", "snapshot_id"),
        Index("ix_fare_quote_clean_quote", "quote_id"),
    )
