"""Maps Akasa Air's fare data to :class:`RawQuote`.

Akasa's spider tries :class:`~apix_collector.strategies.json_endpoint.JsonEndpointStrategy`
first and falls back to
:class:`~apix_collector.strategies.rendered_page.RenderedPageStrategy` — a common
real-world shape is that the rendered page's server-side render embeds the same fare
payload as inline JSON (``window.__FARE_DATA__ = {...}``) rather than a hand-built DOM,
so one mapper handles both acquisition paths: it reads the body as JSON directly, and
falls back to extracting the embedded script only if that fails.

Recorded fixtures: ``fixtures/airline_akasa/DEL-BOM.json`` (JSON endpoint) and
``fixtures/airline_akasa/DEL-BOM.html`` (rendered-page fallback). Recording procedure
is in ``docs/fixtures.md``.
"""

from __future__ import annotations

import json
import re
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

SOURCE_CODE = "airline_akasa"

_EMBEDDED_JSON_RE = re.compile(rb"window\.__FARE_DATA__\s*=\s*(\{.*?\})\s*;", re.DOTALL)

_GOLDEN_SAMPLE: dict[str, Any] = {
    "flights": [
        {
            "flight_no": "QP0001",
            "airline_code": "QP",
            "dep": {"iata": "BLR", "local_time": "2026-01-01T09:00:00"},
            "arr": {"iata": "DEL", "local_time": "2026-01-01T11:30:00"},
            "num_stops": 0,
            "fares": [
                {
                    "fare_type": "SAVER",
                    "class_of_service": "ECONOMY",
                    "fare_breakup": {"base": 1.0, "tax": 1.0, "udf": 1.0},
                    "total": 1.0,
                    "currency_code": "INR",
                    "seats_left": 1,
                    "is_refundable": False,
                    "free_baggage": True,
                }
            ],
        }
    ],
}
KNOWN_GOOD_KEYS: frozenset[str] = frozenset(flatten_keys(_GOLDEN_SAMPLE))


class AkasaMapper:
    """Normalises Akasa's fare payload, however it was acquired."""

    source_code: str = SOURCE_CODE

    def __init__(self, drift_dir: Path | None = None) -> None:
        self._drift_dir = drift_dir or (find_config_dir().parent / "fixtures" / "drift")

    def parse(self, payload: bytes, _context: MapperContext) -> list[RawQuote]:
        data = self._extract_json(payload)
        try:
            flights = data["flights"]
            quotes = [
                self._quote_from(flight, fare) for flight in flights for fare in flight["fares"]
            ]
        except (KeyError, TypeError, ValueError) as exc:
            self._drift(payload, f"response did not match the expected shape: {exc}")
        return quotes

    def _extract_json(self, payload: bytes) -> Any:
        stripped = payload.lstrip()
        if stripped.startswith(b"{"):
            try:
                return json.loads(payload)
            except json.JSONDecodeError as exc:
                self._drift(payload, f"payload is not valid JSON: {exc}")
        match = _EMBEDDED_JSON_RE.search(payload)
        if match is None:
            self._drift(
                payload,
                "payload is neither a JSON body nor a rendered page with an "
                "embedded window.__FARE_DATA__ script",
            )
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            self._drift(payload, f"embedded __FARE_DATA__ is not valid JSON: {exc}")

    def _quote_from(self, flight: dict[str, Any], fare: dict[str, Any]) -> RawQuote:
        breakup = fare["fare_breakup"]
        return RawQuote(
            carrier_iata=flight["airline_code"],
            flight_number=flight["flight_no"],
            dep_datetime_local=datetime.fromisoformat(flight["dep"]["local_time"]),
            arr_datetime_local=datetime.fromisoformat(flight["arr"]["local_time"]),
            stops=int(flight["num_stops"]),
            fare_class=FareClass[fare["class_of_service"]],
            fare_brand=fare["fare_type"],
            base_fare=Decimal(str(breakup["base"])),
            taxes=Decimal(str(breakup["tax"])),
            udf=Decimal(str(breakup["udf"])),
            convenience_fee=None,
            total_fare=Decimal(str(fare["total"])),
            currency=fare["currency_code"],
            seats_shown=int(fare["seats_left"]),
            refundable=bool(fare["is_refundable"]),
            baggage_included=bool(fare["free_baggage"]),
        )

    def _drift(self, payload: bytes, reason: str) -> NoReturn:
        capture_drift(self.source_code, payload, KNOWN_GOOD_KEYS, self._drift_dir, reason=reason)
        raise SchemaDriftError(self.source_code, reason)


__all__ = ["KNOWN_GOOD_KEYS", "AkasaMapper"]
