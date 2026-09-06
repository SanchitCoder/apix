"""Reference data: airports, carriers and the route basket.

These tables are seeded from real published sources (see ``db/seeds/``) and are the
spine every quote hangs off.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apix_core.models.base import Base, pg_enum, uuid_pk
from apix_core.models.enums import CarrierType


class Airport(Base):
    """An airport, keyed by its IATA code."""

    __tablename__ = "airport"

    iata: Mapped[str] = mapped_column(String(3), primary_key=True)
    icao: Mapped[str | None] = mapped_column(String(4), unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    city: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str | None] = mapped_column(String(64))
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lon: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))

    __table_args__ = (
        CheckConstraint("char_length(iata) = 3", name="iata_len"),
        CheckConstraint("lat IS NULL OR (lat BETWEEN -90 AND 90)", name="lat_range"),
        CheckConstraint("lon IS NULL OR (lon BETWEEN -180 AND 180)", name="lon_range"),
        Index("ix_airport_city", "city"),
    )


class Carrier(Base):
    """An airline, keyed by its IATA designator."""

    __tablename__ = "carrier"

    iata: Mapped[str] = mapped_column(String(2), primary_key=True)
    icao: Mapped[str | None] = mapped_column(String(3), unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    carrier_type: Mapped[CarrierType] = mapped_column(
        pg_enum(CarrierType, "carrier_type_enum"), nullable=False
    )

    __table_args__ = (CheckConstraint("char_length(iata) = 2", name="iata_len"),)


class Route(Base):
    """A directional city-pair in the index basket.

    ``dgca_pax_share`` is the route's share of domestic passengers, taken from DGCA
    monthly traffic statistics. It is nullable on purpose: Phase 2 populates it from
    the real DGCA release. An unweighted route is a recorded gap, never a guess.

    ``basket_version`` plus ``active_from``/``active_to`` make the basket itself a
    versioned, time-sliced object, so an index vintage can be recomputed against the
    basket that was in force at the time.
    """

    __tablename__ = "route"

    id: Mapped[uuid.UUID] = uuid_pk()
    origin_iata: Mapped[str] = mapped_column(
        String(3), ForeignKey("airport.iata", ondelete="RESTRICT"), nullable=False
    )
    dest_iata: Mapped[str] = mapped_column(
        String(3), ForeignKey("airport.iata", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(7), nullable=False, unique=True)
    dgca_pax_share: Mapped[Decimal | None] = mapped_column(Numeric(9, 8))
    basket_version: Mapped[str] = mapped_column(String(32), nullable=False)
    active_from: Mapped[date] = mapped_column(Date, nullable=False)
    active_to: Mapped[date | None] = mapped_column(Date)

    origin: Mapped[Airport] = relationship(foreign_keys=[origin_iata], lazy="raise")
    dest: Mapped[Airport] = relationship(foreign_keys=[dest_iata], lazy="raise")

    __table_args__ = (
        CheckConstraint("origin_iata <> dest_iata", name="distinct_endpoints"),
        CheckConstraint(
            "dgca_pax_share IS NULL OR (dgca_pax_share >= 0 AND dgca_pax_share <= 1)",
            name="pax_share_unit_interval",
        ),
        CheckConstraint("active_to IS NULL OR active_to > active_from", name="active_window"),
        UniqueConstraint(
            "origin_iata", "dest_iata", "basket_version", name="uq_route_pair_version"
        ),
        Index("ix_route_basket_version_active", "basket_version", "active_from", "active_to"),
    )
