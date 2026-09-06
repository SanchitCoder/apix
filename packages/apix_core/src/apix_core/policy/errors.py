"""Exceptions raised by the compliance engine.

Each one exists so a caller can distinguish "you may not do this" from "this broke".
None of them are recoverable by retrying harder — a denial is a decision, not a fault.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apix_core.policy.decisions import Decision


class PolicyError(RuntimeError):
    """Base class for everything the PolicyEngine raises."""


class PolicyStartupError(PolicyError):
    """The engine refused to start because the source configuration is not collectable.

    Raised for an enabled source whose ToS verdict is not PERMITTED or whose review is
    older than the maximum review age. Startup failure is deliberate: a stale legal
    review is not a warning condition.
    """


class PolicyDenied(PolicyError):  # noqa: N818 — the name is the API contract
    """A request was refused before any traffic was sent.

    Carries the full :class:`~apix_core.policy.decisions.Decision`, which has already
    been recorded to the decision log by the time this is raised.
    """

    def __init__(self, decision: Decision) -> None:
        super().__init__(f"denied by {decision.rule}: {decision.reason}")
        self.decision = decision


class CaptchaDetected(PolicyError):  # noqa: N818 — the name is the API contract
    """A response body matched a known challenge signature.

    The source has been disabled and the run marked blocked with
    ``error_class="captcha"`` before this is raised. It is never solved, bypassed or
    outsourced — CLAUDE.md guardrail.
    """

    error_class = "captcha"

    def __init__(self, source_code: str, signature: str) -> None:
        super().__init__(
            f"source {source_code!r} presented a challenge ({signature}); "
            "source disabled, run blocked"
        )
        self.source_code = source_code
        self.signature = signature


__all__ = ["CaptchaDetected", "PolicyDenied", "PolicyError", "PolicyStartupError"]
