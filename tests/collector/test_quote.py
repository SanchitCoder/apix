from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from apix_collector.quote import RawQuote

DEP = datetime(2026, 9, 18, 6, 0)


def test_negative_total_fare_is_rejected() -> None:
    with pytest.raises(ValueError, match="total_fare"):
        RawQuote(carrier_iata="6E", total_fare=Decimal("-1"), dep_datetime_local=DEP)


def test_stops_out_of_range_is_rejected() -> None:
    with pytest.raises(ValueError, match="stops"):
        RawQuote(carrier_iata="6E", total_fare=Decimal("1"), dep_datetime_local=DEP, stops=5)


def test_currency_must_be_three_letters() -> None:
    with pytest.raises(ValueError, match="currency"):
        RawQuote(
            carrier_iata="6E", total_fare=Decimal("1"), dep_datetime_local=DEP, currency="INRX"
        )


def test_a_valid_quote_is_accepted() -> None:
    quote = RawQuote(carrier_iata="6E", total_fare=Decimal("4000.00"), dep_datetime_local=DEP)
    assert quote.currency == "INR"
    assert quote.stops == 0
