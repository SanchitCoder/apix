"""The PolicyEngine surface: contract-level assertions.

Behavioural tests live in ``tests/apix_core/policy/``; these pin the parts of the
surface other code is allowed to rely on.
"""

from __future__ import annotations

from apix_core.models.enums import PolicyDecisionOutcome
from apix_core.policy import Decision


def make_decision(outcome: PolicyDecisionOutcome, allowed: bool) -> Decision:
    return Decision(
        allowed=allowed,
        reason="test",
        rule="test",
        outcome=outcome,
        url_hash="0" * 64,
        source_code="test_source",
    )


def test_only_the_allowed_outcome_is_permissive():
    permissive = {o for o in PolicyDecisionOutcome if not o.value.startswith("DENIED")}
    assert permissive == {PolicyDecisionOutcome.ALLOWED}


def test_decisions_carry_their_audit_fields():
    decision = make_decision(PolicyDecisionOutcome.DENIED_ROBOTS, allowed=False)
    assert decision.url_hash
    assert decision.rule
    assert decision.reason
    assert decision.source_code


def test_there_is_a_captcha_denial_outcome():
    """CLAUDE.md guardrail: a CAPTCHA blocks the source. It is never solved.
    (The absence of a solver is asserted in tests/apix_core/policy/test_captcha.py.)"""
    assert PolicyDecisionOutcome.DENIED_CAPTCHA in PolicyDecisionOutcome
