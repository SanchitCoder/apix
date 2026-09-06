from __future__ import annotations

import pytest

from apix_collector.errors import FetchFailed
from apix_collector.session import SessionRotator
from apix_collector.strategies.json_endpoint import JsonEndpointStrategy
from apix_core.models.enums import CollectionMethod
from apix_core.policy import PolicyDenied


def test_fetches_a_real_fixture_through_the_real_policy_engine(
    policy_engine, fixture_server
) -> None:
    strategy = JsonEndpointStrategy()
    url = f"{fixture_server.base_url}/airline_indigo/DEL-BOM.json"
    payload = strategy.fetch(policy_engine=policy_engine, url=url, session=SessionRotator().next())
    assert payload.collection_method is CollectionMethod.PUBLIC_JSON_API
    assert b"6E2341" in payload.body
    assert payload.response.content == payload.body


def test_missing_fixture_raises_fetch_failed_not_retried_here(
    policy_engine, fixture_server
) -> None:
    strategy = JsonEndpointStrategy()
    url = f"{fixture_server.base_url}/airline_indigo/NOPE-NOPE.json"
    with pytest.raises(FetchFailed) as excinfo:
        strategy.fetch(policy_engine=policy_engine, url=url, session=SessionRotator().next())
    assert excinfo.value.status_code == 404


def test_a_url_outside_fixture_replay_is_denied(policy_engine) -> None:
    strategy = JsonEndpointStrategy()
    with pytest.raises(PolicyDenied):
        strategy.fetch(
            policy_engine=policy_engine,
            url="https://www.goindigo.in/api/fare-search",
            session=SessionRotator().next(),
        )
