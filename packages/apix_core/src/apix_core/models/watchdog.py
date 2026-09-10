"""Watchdog tables: personalised-pricing probe observations and their dispersion
statistics.

``PersonalisationProbeObservation`` mirrors ``fare_quote``'s provenance shape
(``run_id``-equivalent via ``collection_run``, ``source_id``, ``content_hash``,
``raw_payload_ref``) because it is the same kind of thing — a priced itinerary as
observed by one source at one instant — with three extra columns identifying which of
the N simultaneous session profiles produced it. Append-only, like ``fare_quote``.

Surge and sell-out-velocity results are deliberately *not* persisted here: both are
cheap to recompute on demand from ``fare_quote``/``fare_quote_clean`` and, unlike a
probe observation, do not carry the same past-vintage auditability requirement a raw
observation does. ``dispersion_stat`` is persisted because it is the output of a
probe that cannot be cheaply re-run (it depends on the specific instant N sessions were
issued), so it is the thing worth keeping.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apix_core.models.base import Base, Money, created_at_col, pg_enum, uuid_pk
from apix_core.models.enums import CollectionMethod, LegalBasis


class PersonalisationProbeObservation(Base):
    """One session profile's observed fare for one flight, within one probe run.

    ``cookie_state``/``ua_class``/``geography_tag`` are stored as plain strings, not a
    native enum, because they are governed by ``config/watchdog.yaml`` (see
    :mod:`apix_core.config.watchdog`), not a fixed domain vocabulary the schema should
    own — a new UA class or geography tag is a config change, not a migration.
    """

    __tablename__ = "personalisation_probe_observation"

    id: Mapped[uuid.UUID] = uuid_pk()
    probed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # --- provenance, mirroring fare_quote --------------------------------------
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
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload_ref: Mapped[str | None] = mapped_column(Text)

    # --- what was queried, and by which profile --------------------------------
    route_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("route.id", ondelete="RESTRICT"), nullable=False
    )
    flight_key: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cookie_state: Mapped[str] = mapped_column(String(32), nullable=False)
    ua_class: Mapped[str] = mapped_column(String(32), nullable=False)
    geography_tag: Mapped[str] = mapped_column(String(32), nullable=False)

    total_fare: Mapped[Decimal] = mapped_column(Money, nullable=False)

    __table_args__ = (
        CheckConstraint("total_fare > 0", name="total_fare_positive"),
        Index(
            "ix_personalisation_probe_observation_flight_probed",
            "source_id",
            "flight_key",
            "probed_at",
        ),
    )


class DispersionStat(Base):
    """One computed dispersion statistic for one probe instance.

    Written from :func:`apix_core.watchdog.dispersion.compute_dispersion`'s output —
    the persisted "per-source dispersion statistic over time" the task asks for.
    """

    __tablename__ = "dispersion_stat"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source.id", ondelete="RESTRICT"), nullable=False
    )
    flight_key: Mapped[str] = mapped_column(String(64), nullable=False)
    probed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    statistic_name: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[Decimal] = mapped_column(Money, nullable=False)
    n_sessions: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        CheckConstraint("n_sessions >= 1", name="n_sessions_positive"),
        CheckConstraint("value >= 0", name="value_non_negative"),
        Index("ix_dispersion_stat_source_flight_probed", "source_id", "flight_key", "probed_at"),
    )


__all__ = ["DispersionStat", "PersonalisationProbeObservation"]
