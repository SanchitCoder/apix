"""Maps Cleartrip's rendered search-results page to :class:`RawQuote`.

Cleartrip's spider uses
:class:`~apix_collector.strategies.rendered_page.RenderedPageStrategy` only: OTA
aggregator result pages are built client-side from multiple supplier calls, so there
is no single internal JSON endpoint to replay. This mapper reads the rendered DOM with
``parsel`` (already a transitive dependency via Scrapy) instead of a JSON shape.

Recorded fixture: ``fixtures/ota_cleartrip/DEL-BOM.html``. Recording procedure is in
``docs/fixtures.md``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from parsel import Selector

from apix_collector.drift import capture_drift
from apix_collector.errors import SchemaDriftError
from apix_collector.quote import RawQuote
from apix_core.config import find_config_dir
from apix_core.models.enums import FareClass

if TYPE_CHECKING:
    from apix_collector.quote import MapperContext

SOURCE_CODE = "ota_cleartrip"

_CARD_SELECTOR = "div.fareCard"

# The attributes/fields every fare card must carry. Used only to produce a legible
# drift reason — HTML has no schema to diff key-for-key the way JSON does.
_REQUIRED_FIELDS = frozenset(
    {
        "data-flight-number",
        "data-carrier",
        "data-stops",
        "data-dep-time",
        "data-arr-time",
        "fareCard__brand",
        "fareCard__cabin",
        "fareCard__baseFare",
        "fareCard__taxes",
        "fareCard__convenienceFee",
        "fareCard__totalFare",
        "fareCard__seats",
        "fareCard__refundable",
    }
)


class CleartripMapper:
    """Normalises Cleartrip's rendered fare-card markup."""

    source_code: str = SOURCE_CODE

    def __init__(self, drift_dir: Path | None = None) -> None:
        self._drift_dir = drift_dir or (find_config_dir().parent / "fixtures" / "drift")

    def parse(self, payload: bytes, _context: MapperContext) -> list[RawQuote]:
        try:
            html = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            self._drift(payload, f"page body is not valid UTF-8 HTML: {exc}")
        selector = Selector(text=html)
        cards = selector.css(_CARD_SELECTOR)
        if not cards and selector.css("div.noFlights"):
            return []  # a genuine "no service on this route/date" result, not drift
        try:
            return [self._quote_from(card) for card in cards]
        except (ValueError, InvalidOperation, TypeError) as exc:
            self._drift(payload, f"fare card did not match the expected markup: {exc}")

    def _quote_from(self, card: Selector) -> RawQuote:
        def attr(name: str) -> str:
            value = card.attrib.get(name)
            if value is None:
                raise ValueError(f"fare card is missing attribute {name!r}")
            return value

        def text(css_class: str) -> str:
            value = card.css(f".{css_class}::text").get()
            if value is None:
                raise ValueError(f"fare card is missing .{css_class}")
            return value.strip()

        return RawQuote(
            carrier_iata=attr("data-carrier"),
            flight_number=attr("data-flight-number"),
            dep_datetime_local=datetime.fromisoformat(attr("data-dep-time")),
            arr_datetime_local=datetime.fromisoformat(attr("data-arr-time")),
            stops=int(attr("data-stops")),
            fare_class=FareClass[text("fareCard__cabin")],
            fare_brand=text("fareCard__brand"),
            base_fare=Decimal(text("fareCard__baseFare")),
            taxes=Decimal(text("fareCard__taxes")),
            udf=None,  # OTA markup does not break UDF out from base fare
            convenience_fee=Decimal(text("fareCard__convenienceFee")),
            total_fare=Decimal(text("fareCard__totalFare")),
            currency="INR",
            seats_shown=int(text("fareCard__seats")),
            refundable=text("fareCard__refundable").lower() == "true",
            baggage_included=None,
        )

    def _drift(self, payload: bytes, reason: str) -> NoReturn:
        capture_drift(self.source_code, payload, frozenset(), self._drift_dir, reason=reason)
        raise SchemaDriftError(self.source_code, reason)


__all__ = ["_REQUIRED_FIELDS", "CleartripMapper"]
