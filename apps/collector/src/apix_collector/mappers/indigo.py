"""Maps IndiGo's internal fare-search JSON API to :class:`RawQuote`.

Recorded fixture: ``fixtures/airline_indigo/DEL-BOM.json``. Recording procedure is in
``docs/fixtures.md``.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from apix_collector.drift import capture_drift, flatten_keys
from apix_collector.errors import SchemaDriftError
from apix_collector.quote import RawQuote
from apix_core.config import find_config_dir
from apix_core.models.enums import FareClass

if TYPE_CHECKING:
    from apix_collector.quote import MapperContext

SOURCE_CODE = "airline_indigo"

# A minimal, valid sample of the shape this mapper expects. Never fetched from
# anywhere — it exists purely so ``KNOWN_GOOD_KEYS`` is derived from one place instead
# of hand-maintained as a list of path strings that could silently drift from the code
# reading them.
_GOLDEN_SAMPLE: dict[str, Any] = {
    "searchId": "sample",
    "itineraries": [
        {
            "flightNumber": "6E0001",
            "carrier": "6E",
            "departure": {"airport": "DEL", "dateTime": "2026-01-01T06:00:00"},
            "arrival": {"airport": "BOM", "dateTime": "2026-01-01T08:10:00"},
            "stops": 0,
            "fareOptions": [
                {
                    "brand": "SAVER",
                    "cabin": "ECONOMY",
                    "baseFare": 1.0,
                    "taxes": 1.0,
                    "udf": 1.0,
                    "totalFare": 1.0,
                    "currency": "INR",
                    "seatsRemaining": 1,
                    "refundable": False,
                    "baggageIncluded": True,
                }
            ],
        }
    ],
}
KNOWN_GOOD_KEYS: frozenset[str] = frozenset(flatten_keys(_GOLDEN_SAMPLE))


class IndigoMapper:
    """Normalises IndiGo's JSON fare-search response."""

    source_code: str = SOURCE_CODE

    def __init__(self, drift_dir: Path | None = None) -> None:
        self._drift_dir = drift_dir or (find_config_dir().parent / "fixtures" / "drift")

    def parse(self, payload: bytes, _context: MapperContext) -> list[RawQuote]:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            self._drift(payload, f"payload is not valid JSON: {exc}")
        try:
            itineraries = data["itineraries"]
            quotes = [
                self._quote_from(itinerary, option)
                for itinerary in itineraries
                for option in itinerary["fareOptions"]
            ]
        except (KeyError, TypeError, ValueError) as exc:
            self._drift(payload, f"response did not match the expected shape: {exc}")
        return quotes

    def _quote_from(self, itinerary: dict[str, Any], option: dict[str, Any]) -> RawQuote:
        return RawQuote(
            carrier_iata=itinerary["carrier"],
            flight_number=itinerary["flightNumber"],
            dep_datetime_local=datetime.fromisoformat(itinerary["departure"]["dateTime"]),
            arr_datetime_local=datetime.fromisoformat(itinerary["arrival"]["dateTime"]),
            stops=int(itinerary["stops"]),
            fare_class=FareClass[option["cabin"]],
            fare_brand=option["brand"],
            base_fare=Decimal(str(option["baseFare"])),
            taxes=Decimal(str(option["taxes"])),
            udf=Decimal(str(option["udf"])),
            convenience_fee=None,  # airline's own site: no OTA convenience fee
            total_fare=Decimal(str(option["totalFare"])),
            currency=option["currency"],
            seats_shown=int(option["seatsRemaining"]),
            refundable=bool(option["refundable"]),
            baggage_included=bool(option["baggageIncluded"]),
        )

    def _drift(self, payload: bytes, reason: str) -> NoReturn:
        capture_drift(self.source_code, payload, KNOWN_GOOD_KEYS, self._drift_dir, reason=reason)
        raise SchemaDriftError(self.source_code, reason)


__all__ = ["KNOWN_GOOD_KEYS", "IndigoMapper"]
