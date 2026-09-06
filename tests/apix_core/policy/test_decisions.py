"""Decision logs: the audit trail is written whatever the backend."""

from __future__ import annotations

import uuid

from structlog.testing import capture_logs

from apix_core.models.collection import PolicyDecision
from apix_core.models.enums import PolicyDecisionOutcome
from apix_core.policy import DatabaseDecisionLog, Decision, InMemoryDecisionLog


def make_decision(**overrides) -> Decision:
    values = {
        "allowed": False,
        "reason": "path matches disallowed prefix",
        "rule": "disallowed_paths",
        "outcome": PolicyDecisionOutcome.DENIED_PATH,
        "url_hash": "ab" * 32,
        "source_code": "test_source",
        "retry_after_s": None,
    }
    values.update(overrides)
    return Decision(**values)


def test_in_memory_log_keeps_order():
    log = InMemoryDecisionLog()
    first = make_decision(rule="robots")
    second = make_decision(rule="rate_limit")
    log.record(first)
    log.record(second)
    assert log.decisions == [first, second]


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class FakeSession:
    """Duck-typed sqlalchemy Session: enough for DatabaseDecisionLog."""

    def __init__(self, source_id: uuid.UUID) -> None:
        self.source_id = source_id
        self.added: list = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def execute(self, statement):
        return FakeResult(self.source_id)

    def add(self, instance) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commits += 1


def test_database_log_writes_one_committed_row():
    source_id = uuid.uuid4()
    session = FakeSession(source_id)
    log = DatabaseDecisionLog(lambda: session)
    decision = make_decision()

    log.record(decision)

    (row,) = session.added
    assert isinstance(row, PolicyDecision)
    assert row.source_id == source_id
    assert row.url_hash == decision.url_hash
    assert row.decision is PolicyDecisionOutcome.DENIED_PATH
    assert row.reason == decision.reason
    assert session.commits == 1


def test_database_log_reports_unattributable_decisions_instead_of_dropping_them():
    """A denial for an unconfigured host has no source row to reference; it still
    lands in the structured log rather than vanishing."""
    session = FakeSession(uuid.uuid4())
    log = DatabaseDecisionLog(lambda: session)

    with capture_logs() as logs:
        log.record(make_decision(source_code=None))

    assert session.added == []
    assert any(e["event"] == "policy_decision_unattributable" for e in logs)
