"""The canonical shape every source mapper normalises its response into.

A mapper never touches the database, the object store or ``apix_core.models`` — it
only ever produces ``RawQuote`` values from bytes. ``apix_collector.run`` is the only
place a ``RawQuote`` becomes a persisted ``FareQuote`` row, once it has resolved
``route_id``, ``run_id`` and the provenance stamp that a mapper has no business
computing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from apix_core.models.enums import FareClass


@dataclass(frozen=True, slots=True)
class RawQuote:
    """One priced itinerary as a mapper read it off the source's response."""

    carrier_iata: str
    total_fare: Decimal
    dep_datetime_local: datetime
    flight_number: str | None = None
    arr_datetime_local: datetime | None = None
    stops: int = 0
    fare_class: FareClass = FareClass.ECONOMY
    fare_brand: str | None = None
    base_fare: Decimal | None = None
    taxes: Decimal | None = None
    udf: Decimal | None = None
    convenience_fee: Decimal | None = None
    currency: str = "INR"
    seats_shown: int | None = None
    refundable: bool | None = None
    baggage_included: bool | None = None

    def __post_init__(self) -> None:
        if self.total_fare < 0:
            raise ValueError(f"total_fare must be non-negative, got {self.total_fare}")
        if not (0 <= self.stops <= 4):
            raise ValueError(f"stops must be between 0 and 4, got {self.stops}")
        if len(self.currency) != 3:
            raise ValueError(f"currency must be an ISO-4217 code, got {self.currency!r}")


@dataclass(frozen=True, slots=True)
class MapperContext:
    """What a mapper is told about the request that produced the payload it parses.

    None of this is *in* the payload — it is the query the spider issued — but a
    mapper needs it to stamp ``travel_date``/``query_date`` onto quotes whose response
    shape does not always repeat them per itinerary.
    """

    route_code: str
    travel_date: date
    query_date: date


__all__ = ["MapperContext", "RawQuote"]
