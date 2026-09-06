"""The Decision record and the logs it is written to.

Every call to ``PolicyEngine.check`` produces exactly one :class:`Decision` and hands
it to a :class:`DecisionLog` before returning — allowed and denied alike. The log is
the audit trail proving the engine was consulted (CLAUDE.md principle 3), so there is
no code path that skips it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import structlog
from sqlalchemy import select

from apix_core.models.collection import PolicyDecision, Source

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

    from apix_core.models.enums import PolicyDecisionOutcome

_log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Decision:
    """The engine's answer about one URL.

    ``rule`` names the check that decided (``source_enabled``, ``tos``, ``robots``,
    ``allowed_paths``, ``disallowed_paths``, ``rate_limit``, ``cooling_off``,
    ``captcha`` or ``allowed``), so an audit can see not just that a URL was denied
    but which gate denied it.
    """

    allowed: bool
    reason: str
    rule: str
    outcome: PolicyDecisionOutcome
    url_hash: str
    source_code: str | None
    retry_after_s: float | None = None


class DecisionLog(Protocol):
    """Anything that can persist a Decision."""

    def record(self, decision: Decision) -> None:
        """Persist ``decision``. Must not swallow it — the row is the audit trail."""
        ...


class InMemoryDecisionLog:
    """Decision log for tests and dry runs. Keeps every decision, in order."""

    def __init__(self) -> None:
        self.decisions: list[Decision] = []

    def record(self, decision: Decision) -> None:
        self.decisions.append(decision)


class DatabaseDecisionLog:
    """Writes each decision as a ``policy_decision`` row.

    Takes a session factory rather than a session: each decision is its own short
    transaction, committed immediately, so the audit row survives even if the request
    that follows it crashes the process.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def record(self, decision: Decision) -> None:
        if decision.source_code is None:
            # A URL whose host matches no configured source has no source row to
            # attach the decision to. The denial still happened and is still logged —
            # just to the structured log rather than the table.
            _log.error(
                "policy_decision_unattributable",
                url_hash=decision.url_hash,
                outcome=decision.outcome.value,
                reason=decision.reason,
            )
            return
        with self._session_factory() as session:
            source_id = session.execute(
                select(Source.id).where(Source.code == decision.source_code)
            ).scalar_one()
            session.add(
                PolicyDecision(
                    source_id=source_id,
                    url_hash=decision.url_hash,
                    decision=decision.outcome,
                    reason=decision.reason,
                )
            )
            session.commit()


__all__ = [
    "DatabaseDecisionLog",
    "Decision",
    "DecisionLog",
    "InMemoryDecisionLog",
]
