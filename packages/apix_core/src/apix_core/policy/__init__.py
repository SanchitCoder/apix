"""Compliance engine.

Every outbound request to a source website goes through :meth:`PolicyEngine.request`.
There is no other code path — that is guardrail one in CLAUDE.md, and it is enforced
by an AST scan in ``tests/test_egress_only.py`` rather than described in a README:
this package is the only production module permitted to import an HTTP client.
"""

from __future__ import annotations

from apix_core.policy.captcha import detect_challenge
from apix_core.policy.decisions import (
    DatabaseDecisionLog,
    Decision,
    DecisionLog,
    InMemoryDecisionLog,
)
from apix_core.policy.engine import PolicyEngine, load_policy_engine
from apix_core.policy.errors import (
    CaptchaDetected,
    PolicyDenied,
    PolicyError,
    PolicyStartupError,
)
from apix_core.policy.ratelimit import RateLimitVerdict, TokenBucketLimiter
from apix_core.policy.robots import RobotsCache, RobotsInfo, extract_crawl_delay

__all__ = [
    "CaptchaDetected",
    "DatabaseDecisionLog",
    "Decision",
    "DecisionLog",
    "InMemoryDecisionLog",
    "PolicyDenied",
    "PolicyEngine",
    "PolicyError",
    "PolicyStartupError",
    "RateLimitVerdict",
    "RobotsCache",
    "RobotsInfo",
    "TokenBucketLimiter",
    "detect_challenge",
    "extract_crawl_delay",
    "load_policy_engine",
]
