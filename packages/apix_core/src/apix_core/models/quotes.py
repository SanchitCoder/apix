"""``fare_quote`` — the raw observation table. Append-only, never mutated.

This is the evidence base for every published number. A row here is a single priced
itinerary as it was displayed by one source at one instant, together with everything
needed to prove where it came from and why we were entitled to collect it.

TimescaleDB
-----------
``fare_quote`` is a hypertable partitioned on ``collected_at``. Timescale requires the
partitioning column to participate in every unique index, so the primary key is the
composite ``(id, collected_at)`` rather than ``id`` alone. ``id`` is still a UUID and
still globally unique in practice; the timestamp is carried alongside it so that
foreign keys into this table (see ``fare_quote_clean``) remain real, enforced
constraints rather than a documented convention.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apix_core.models.base import Base, Money, pg_enum
from apix_core.models.enums import CollectionMethod, FareClass, LegalBasis


class FareQuote(Base):
    """One observed fare. Append-only: no UPDATE, no DELETE, ever.

    Corrections are expressed downstream in ``fare_quote_clean``, never by editing a
    row here. The database enforces this with a rule installed by the migration.
    """

    __tablename__ = "fare_quote"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # Partition key. Part of the primary key because Timescale requires it.
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=text("now()")
    )

    # --- provenance ------------------------------------------------------------
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collection_run.id", ondelete="RESTRICT"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source.id", ondelete="RESTRICT"), nullable=False
    )
    collection_method: Mapped[CollectionMethod] = mapped_column(
        pg_enum(CollectionMethod, "collection_method_enum"), nullable=False
    )
    legal_basis: Mapped[LegalBasis] = mapped_column(
        pg_enum(LegalBasis, "legal_basis_enum"), nullable=False
    )
    source_url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Hash of the normalised quote payload — de-duplicates re-observations of an
    # unchanged fare and detects silent source-side changes.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Pointer into object storage for the raw response, not the response itself.
    raw_payload_ref: Mapped[str | None] = mapped_column(Text)

    # --- what was priced -------------------------------------------------------
    route_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("route.id", ondelete="RESTRICT"), nullable=False
    )
    carrier_iata: Mapped[str] = mapped_column(
        String(2), ForeignKey("carrier.iata", ondelete="RESTRICT"), nullable=False
    )
    flight_number: Mapped[str | None] = mapped_column(String(8))
    # Local airport time, deliberately naive: "07:15 at DEL" is the consumer-facing
    # fact, and the UTC offset is recoverable from the airport.
    dep_datetime_local: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    arr_datetime_local: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    stops: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    travel_date: Mapped[date] = mapped_column(Date, nullable=False)
    query_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Denormalised (travel_date - query_date). Stored, not computed, because it is the
    # single most-filtered column in the whole system.
    advance_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    fare_class: Mapped[FareClass] = mapped_column(
        pg_enum(FareClass, "fare_class_enum"),
        nullable=False,
        server_default=text("'ECONOMY'"),
    )
    fare_brand: Mapped[str | None] = mapped_column(String(64))

    # --- the money -------------------------------------------------------------
    base_fare: Mapped[Decimal | None] = mapped_column(Money)
    taxes: Mapped[Decimal | None] = mapped_column(Money)
    udf: Mapped[Decimal | None] = mapped_column(Money)  # user development fee
    convenience_fee: Mapped[Decimal | None] = mapped_column(Money)
    total_fare: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'INR'"))

    # --- displayed attributes --------------------------------------------------
    seats_shown: Mapped[int | None] = mapped_column(Integer)
    refundable: Mapped[bool | None] = mapped_column(Boolean)
    baggage_included: Mapped[bool | None] = mapped_column(Boolean)

    __table_args__ = (
        CheckConstraint("total_fare >= 0", name="total_fare_non_negative"),
        CheckConstraint("base_fare IS NULL OR base_fare >= 0", name="base_fare_non_negative"),
        CheckConstraint("stops >= 0 AND stops <= 4", name="stops_plausible"),
        CheckConstraint("advance_days >= 0 AND advance_days <= 365", name="advance_days_range"),
        CheckConstraint("travel_date >= query_date", name="travel_after_query"),
        CheckConstraint("char_length(currency) = 3", name="currency_iso4217"),
        CheckConstraint("seats_shown IS NULL OR seats_shown >= 0", name="seats_shown_non_negative"),
        # Dashboard query patterns.
        Index("ix_fare_quote_route_travel_date", "route_id", "travel_date"),
        Index("ix_fare_quote_route_advance_query", "route_id", "advance_days", "query_date"),
        Index("ix_fare_quote_collected_at", "collected_at"),
        Index("ix_fare_quote_run", "run_id"),
        Index("ix_fare_quote_content_hash", "content_hash"),
        # De-duplication: the same fare re-observed at the same instant is one row.
        Index(
            "uq_fare_quote_dedup",
            "content_hash",
            "collected_at",
            unique=True,
        ),
    )
