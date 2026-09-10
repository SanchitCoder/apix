"""Schemathesis contract tests against the generated OpenAPI document.

Run against the real, seeded database (``api_schema`` in ``tests/api/conftest.py``) —
DONE WHEN: schemathesis passes with no failures. A researcher key is presented on every
generated request so both public and microdata/draft-gated paths are exercised; an
absent or wrong role is exactly what the auth unit tests in ``test_auth.py`` cover.
"""

from __future__ import annotations

import pytest
import schemathesis
from hypothesis import HealthCheck, settings

from tests.api.conftest import RESEARCHER_API_KEY
from tests.conftest import requires_docker

pytestmark = [pytest.mark.integration, requires_docker]

schema = schemathesis.pytest.from_fixture("api_schema")


@schema.parametrize()
@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_api_contract(case: schemathesis.Case) -> None:
    case.call_and_validate(headers={"X-API-Key": RESEARCHER_API_KEY})
