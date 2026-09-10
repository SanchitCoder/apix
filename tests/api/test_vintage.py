"""The vintage contract: ``/v1/index/vintage`` resolves against
``index_run.vintage_date`` — "what did we believe on date X" — not merely the latest
run. Three real vintages of one period, each from its own index run over real (if
synthetic) ``fare_quote`` data, prove it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apix_scheduler.index_run import compute_and_persist
from tests.api.conftest import (
    FIRST_AS_OF,
    LATEST_SEEDED_DATE,
    ROUTE_SERIES,
    SECOND_AS_OF,
    WINDOW_DAYS,
)
from tests.conftest import requires_docker

pytestmark = [pytest.mark.integration, requires_docker]

PERIOD = FIRST_AS_OF.replace(day=1)
THIRD_AS_OF = LATEST_SEEDED_DATE


@pytest.fixture(scope="module")
def three_vintages(seeded_database_url: str) -> None:
    """``seeded_database_url`` already published two vintages (see conftest); this adds
    a third, later one of the same period, so all three assertions below have a real
    run to resolve against.
    """
    engine = create_engine(seeded_database_url)
    try:
        with Session(engine) as session:
            compute_and_persist(session, THIRD_AS_OF, WINDOW_DAYS)
    finally:
        engine.dispose()


async def _vintage(api_async_client, as_of: str) -> dict:
    response = await api_async_client.get(
        "/v1/index/vintage",
        params={"series": ROUTE_SERIES, "period": PERIOD.isoformat(), "as_of": as_of},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_before_any_run_the_period_is_not_yet_known(api_async_client, three_vintages) -> None:
    response = await api_async_client.get(
        "/v1/index/vintage",
        params={"series": ROUTE_SERIES, "period": PERIOD.isoformat(), "as_of": PERIOD.isoformat()},
    )
    assert response.status_code == 404


async def test_vintage_resolves_to_the_run_in_force_on_the_asked_date(
    api_async_client, three_vintages
) -> None:
    first = await _vintage(api_async_client, (FIRST_AS_OF + timedelta(days=1)).isoformat())
    second = await _vintage(api_async_client, (SECOND_AS_OF + timedelta(days=1)).isoformat())
    third = await _vintage(api_async_client, THIRD_AS_OF.isoformat())

    # Three genuinely distinct runs answered the same question at three points in time.
    assert len({first["index_run_id"], second["index_run_id"], third["index_run_id"]}) == 3

    # Asking again for a date within the first run's reign returns the same vintage —
    # the vintage lookup is a function of (period, as_of), not of when you happen to ask.
    repeat_first = await _vintage(api_async_client, FIRST_AS_OF.isoformat())
    assert repeat_first["index_run_id"] == first["index_run_id"]

    # The second and third runs recomputed an already-published period: that is a
    # revision, and revision_log says so rather than silently swapping the number.
    assert second["revised_from"] is not None
    assert second["revision_reason"]
    assert third["revised_from"] is not None
    assert third["revision_reason"]


async def test_asking_before_the_first_run_never_returns_a_later_vintage(
    api_async_client, three_vintages
) -> None:
    """A date strictly before the first run's vintage_date must not leak a later value —
    that would mean answering "what did we believe on date X" with something nobody
    believed yet on date X.
    """
    response = await api_async_client.get(
        "/v1/index/vintage",
        params={
            "series": ROUTE_SERIES,
            "period": PERIOD.isoformat(),
            "as_of": (FIRST_AS_OF - timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 404
