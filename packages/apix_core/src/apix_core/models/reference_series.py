"""External reference series the nowcast and back-test modules score against.

Every table here follows the same "loader ready, data NOT loaded" discipline as
``route.dgca_pax_share`` (see ``docs/data-sources.md``): the schema exists so the
maths can be built and tested against real shapes, but no row is inserted except by a
human running a loader against a named, cited official release
(``apps/scheduler``'s ``atf_loader``/``cpi_loader``/``dgca_fare_loader``). Each row
carries ``source_note`` for that citation, and ``collected_at`` so a later, corrected
release lands as a new row rather than an overwrite — the same append-only vintage
discipline as ``fare_quote`` and ``index_value``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apix_core.models.base import Base, IndexNumber, Money, created_at_col, uuid_pk


class AtfPrice(Base):
    """One published ATF (aviation turbine fuel) price point.

    ``price_per_kl`` is in INR per kilolitre, the unit Indian oil marketing companies
    publish their ATF price notifications in.
    """

    __tablename__ = "atf_price"

    id: Mapped[uuid.UUID] = uuid_pk()
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    city: Mapped[str] = mapped_column(String(64), nullable=False)
    price_per_kl: Mapped[Decimal] = mapped_column(Money, nullable=False)
    source_note: Mapped[str] = mapped_column(Text, nullable=False)
    collected_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        CheckConstraint("price_per_kl > 0", name="price_per_kl_positive"),
        Index("ix_atf_price_date_city", "price_date", "city"),
    )


class CpiAirfareIndex(Base):
    """One published value of the official CPI air-fare item index.

    Append-only like ``index_value``: a later MoSPI revision of a period is a new row
    with a later ``release_date``, never an overwrite of the earlier one.
    """

    __tablename__ = "cpi_airfare_index"

    id: Mapped[uuid.UUID] = uuid_pk()
    period: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal] = mapped_column(IndexNumber, nullable=False)
    base_year: Mapped[str] = mapped_column(String(16), nullable=False)
    release_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_note: Mapped[str] = mapped_column(Text, nullable=False)
    collected_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        CheckConstraint("value > 0", name="value_positive"),
        Index("ix_cpi_airfare_index_period_release", "period", "release_date"),
    )


class DgcaFareReference(Base):
    """One published DGCA (or other cited official benchmark) average fare for a
    route and period. See ``docs/data-sources.md`` for the provenance caveat: as
    verified when this table was introduced, DGCA's Monthly Domestic Traffic release
    publishes passenger counts, not average fares — this table stays empty until a
    real, cited fare benchmark is loaded, whatever its ultimate source turns out to be.
    """

    __tablename__ = "dgca_fare_reference"

    id: Mapped[uuid.UUID] = uuid_pk()
    route_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("route.id", ondelete="RESTRICT"), nullable=False
    )
    period: Mapped[date] = mapped_column(Date, nullable=False)
    avg_fare: Mapped[Decimal] = mapped_column(Money, nullable=False)
    source_note: Mapped[str] = mapped_column(Text, nullable=False)
    collected_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        CheckConstraint("avg_fare > 0", name="avg_fare_positive"),
        Index("ix_dgca_fare_reference_route_period", "route_id", "period"),
    )


class RailFare(Base):
    """One published AC-2 rail fare for a corridor, effective from a date.

    ``corridor_code`` is whatever identifier the eventual rail-fare source uses for a
    corridor — mapped from a basket route via ``config/watchdog.yaml``'s
    ``rail.corridor_map`` (see :mod:`apix_core.config.watchdog`). No real rail-fare
    source is integrated yet (see :class:`apix_core.watchdog.rail.NotImplementedRailFareSource`
    and docs/data-sources.md); this table is the interface's landing place once one is.
    """

    __tablename__ = "rail_fare"

    id: Mapped[uuid.UUID] = uuid_pk()
    corridor_code: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    fare: Mapped[Decimal] = mapped_column(Money, nullable=False)
    source_note: Mapped[str] = mapped_column(Text, nullable=False)
    collected_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        CheckConstraint("fare > 0", name="fare_positive"),
        Index("ix_rail_fare_corridor_effective", "corridor_code", "effective_date"),
    )


__all__ = ["AtfPrice", "CpiAirfareIndex", "DgcaFareReference", "RailFare"]
