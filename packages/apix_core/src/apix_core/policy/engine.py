"""The PolicyEngine: the single egress point for all collection traffic.

``PolicyEngine.request`` is the only place in this codebase that performs an outbound
HTTP request to a source. That is not a convention — ``tests/test_egress_only.py``
scans every production module's AST and fails if anything else imports an HTTP client.

The engine refuses to start on a config whose enabled sources are not collectable
(unreviewed, non-permissive or stale ToS), consults every gate in a fixed order for
every URL, and records every decision — allowed or denied — before acting on it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import time as _wall_clock
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx
import structlog

from apix_core.config.loader import find_config_dir, load_config
from apix_core.config.sources import SourcesConfig
from apix_core.models.enums import PolicyDecisionOutcome, TosVerdict
from apix_core.policy.captcha import detect_challenge
from apix_core.policy.decisions import Decision, DecisionLog
from apix_core.policy.errors import CaptchaDetected, PolicyDenied, PolicyStartupError
from apix_core.policy.ratelimit import TokenBucketLimiter
from apix_core.policy.robots import RobotsCache
from apix_core.provenance.hashing import hash_url

if TYPE_CHECKING:
    from collections.abc import Callable

    import redis

    from apix_core.config.sources import SourceEntry

_log = structlog.get_logger(__name__)

_COOLOFF_KEY = "apix:policy:cooloff:"
_FAILURES_KEY = "apix:policy:failures:"

#: HTTP statuses that count as the source pushing back on collection.
_PUSHBACK_STATUSES = frozenset({403, 429})


class PolicyEngine:
    """Gatekeeper for all outbound collection traffic.

    Order of gates in :meth:`check`, fixed and exhaustive:

    1. the source — configured, enabled, not cooling off, ToS still permissive;
    2. robots.txt — cached, ETag-revalidated, honoured without exception;
    3. the configured ``allowed_paths`` / ``disallowed_paths`` lists;
    4. the Redis rate limiter (token bucket + hourly cap + crawl delay).

    Every call writes one row to the decision log, whatever the outcome.
    """

    def __init__(
        self,
        *,
        config: SourcesConfig,
        redis_client: redis.Redis,
        decision_log: DecisionLog,
        user_agent: str,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = _wall_clock,
        max_review_age_days: int = 180,
        cooling_off_s: float = 3600.0,
        failures_to_disable: int = 3,
        request_timeout_s: float = 30.0,
        mark_run_blocked: Callable[[str, str], None] | None = None,
    ) -> None:
        self._config = config
        self._redis = redis_client
        self._decision_log = decision_log
        self._user_agent = user_agent
        self._clock = clock
        self._max_review_age = timedelta(days=max_review_age_days)
        self._cooling_off_s = cooling_off_s
        self._failures_to_disable = failures_to_disable
        self._mark_run_blocked = mark_run_blocked
        self._validate_startup()
        self._client = httpx.Client(
            transport=transport,
            headers={"User-Agent": user_agent},
            timeout=request_timeout_s,
            follow_redirects=False,
        )
        self._robots = RobotsCache(redis_client, self._client, user_agent=user_agent, clock=clock)
        self._limiter = TokenBucketLimiter(redis_client, clock=clock)
        self._sources = list(config.sources)

    # ------------------------------------------------------------- startup ----

    def _validate_startup(self) -> None:
        """Refuse to construct an engine around a non-collectable configuration.

        The Pydantic schema already blocks enabling an unreviewed source; this is the
        second, independent enforcement of the same rule plus the one the schema
        cannot express: a review has a shelf life. ``model_construct`` or a hand-built
        config gets no further than this.
        """
        now = self._now()
        problems: list[str] = []
        for source in self._config.sources:
            if not source.enabled:
                continue
            policy = source.policy
            if policy.tos_verdict is not TosVerdict.PERMITTED:
                problems.append(
                    f"{source.code}: enabled but tos_verdict is {policy.tos_verdict.value}"
                )
                continue
            reviewed_at = policy.tos_reviewed_at
            if reviewed_at is None:
                problems.append(f"{source.code}: enabled but tos_reviewed_at is unset")
                continue
            if reviewed_at.tzinfo is None:
                reviewed_at = reviewed_at.replace(tzinfo=UTC)
            age = now - reviewed_at
            if age > self._max_review_age:
                problems.append(
                    f"{source.code}: ToS review of {reviewed_at.date().isoformat()} is "
                    f"{age.days} days old (limit {self._max_review_age.days}); "
                    "a fresh legal review is required before collection can resume"
                )
        if problems:
            raise PolicyStartupError(
                "PolicyEngine refuses to start; enabled sources are not collectable: "
                + "; ".join(problems)
            )

    # --------------------------------------------------------------- check ----

    def check(self, url: str, user_agent: str | None = None) -> Decision:
        """Decide whether ``url`` may be fetched right now, and record the decision."""
        ua = user_agent or self._user_agent
        url_hash = hash_url(url)
        host = (urlsplit(url).hostname or "").lower()
        source = self._match_source(host)
        if source is None:
            return self._decide(
                allowed=False,
                rule="source",
                outcome=PolicyDecisionOutcome.DENIED_SOURCE_DISABLED,
                reason=f"no source is configured for host {host!r}; unknown hosts are denied",
                url_hash=url_hash,
                source_code=None,
            )

        deny = (
            self._check_source(source)
            or self._check_robots(source, ua, url)
            or self._check_paths(source, url)
            or self._check_rate(source)
        )
        if deny is not None:
            outcome, rule, reason, retry_after_s = deny
            return self._decide(
                allowed=False,
                rule=rule,
                outcome=outcome,
                reason=reason,
                url_hash=url_hash,
                source_code=source.code,
                retry_after_s=retry_after_s,
            )
        return self._decide(
            allowed=True,
            rule="allowed",
            outcome=PolicyDecisionOutcome.ALLOWED,
            reason="source enabled, robots.txt allows, path permitted, rate limit granted",
            url_hash=url_hash,
            source_code=source.code,
        )

    def _check_source(
        self, source: SourceEntry
    ) -> tuple[PolicyDecisionOutcome, str, str, float | None] | None:
        if not source.enabled:
            return (
                PolicyDecisionOutcome.DENIED_SOURCE_DISABLED,
                "source_enabled",
                f"source {source.code!r} is disabled",
                None,
            )
        cooloff_ttl = int(self._redis.ttl(_COOLOFF_KEY + source.code))
        if cooloff_ttl > 0:
            return (
                PolicyDecisionOutcome.DENIED_SOURCE_DISABLED,
                "cooling_off",
                f"source {source.code!r} is cooling off after repeated failures",
                float(cooloff_ttl),
            )
        policy = source.policy
        if policy.tos_verdict is not TosVerdict.PERMITTED:
            return (
                PolicyDecisionOutcome.DENIED_TOS,
                "tos",
                f"tos_verdict for {source.code!r} is {policy.tos_verdict.value}, not PERMITTED",
                None,
            )
        reviewed_at = policy.tos_reviewed_at
        if reviewed_at is not None and reviewed_at.tzinfo is None:
            reviewed_at = reviewed_at.replace(tzinfo=UTC)
        if reviewed_at is None or self._now() - reviewed_at > self._max_review_age:
            return (
                PolicyDecisionOutcome.DENIED_TOS,
                "tos",
                f"ToS review for {source.code!r} is missing or older than "
                f"{self._max_review_age.days} days",
                None,
            )
        return None

    def _check_robots(
        self, source: SourceEntry, user_agent: str, url: str
    ) -> tuple[PolicyDecisionOutcome, str, str, float | None] | None:
        robots_url = source.policy.robots_url
        if robots_url is None:
            return None
        info = self._robots.get(source.domain, robots_url)
        if not info.allows(user_agent, url):
            return (
                PolicyDecisionOutcome.DENIED_ROBOTS,
                "robots",
                f"robots.txt for {source.domain} disallows this path for {user_agent!r}",
                None,
            )
        return None

    def _check_paths(
        self, source: SourceEntry, url: str
    ) -> tuple[PolicyDecisionOutcome, str, str, float | None] | None:
        path = urlsplit(url).path or "/"
        policy = source.policy
        for prefix in policy.disallowed_paths:
            if path.startswith(prefix):
                return (
                    PolicyDecisionOutcome.DENIED_PATH,
                    "disallowed_paths",
                    f"path {path!r} matches disallowed prefix {prefix!r}",
                    None,
                )
        if policy.allowed_paths and not any(path.startswith(p) for p in policy.allowed_paths):
            return (
                PolicyDecisionOutcome.DENIED_PATH,
                "allowed_paths",
                f"path {path!r} is outside the allowed paths {policy.allowed_paths}",
                None,
            )
        return None

    def _check_rate(
        self, source: SourceEntry
    ) -> tuple[PolicyDecisionOutcome, str, str, float | None] | None:
        policy = source.policy
        crawl_delay = policy.crawl_delay_s
        if policy.robots_url is not None:
            info = self._robots.get(source.domain, policy.robots_url)
            if info.crawl_delay_s is not None:
                crawl_delay = max(crawl_delay, info.crawl_delay_s)
        verdict = self._limiter.take(
            source.domain,
            crawl_delay_s=crawl_delay,
            max_requests_per_hour=policy.max_requests_per_hour,
        )
        if not verdict.granted:
            return (
                PolicyDecisionOutcome.DENIED_RATE_LIMIT,
                "rate_limit",
                f"rate limiter refused ({verdict.rule}); retry in {verdict.retry_after_s:.1f}s",
                verdict.retry_after_s,
            )
        return None

    # ------------------------------------------------------------- request ----

    def request(self, url: str, *, method: str = "GET", **kwargs: Any) -> httpx.Response:
        """Fetch ``url`` if and only if :meth:`check` allows it.

        This is the ONLY egress point in the codebase. On a denial it raises
        :class:`PolicyDenied` without touching the network. A challenge in the
        response disables the source and raises :class:`CaptchaDetected`; repeated
        403/429 pushback disables the source for a cooling-off period.
        """
        decision = self.check(url, user_agent=kwargs.pop("user_agent", None))
        if not decision.allowed:
            raise PolicyDenied(decision)
        source = self._match_source((urlsplit(url).hostname or "").lower())
        assert source is not None  # check() only allows URLs it matched to a source
        response = self._client.request(method, url, **kwargs)

        signature = detect_challenge(response.content)
        if signature is not None:
            self._handle_challenge(source.code, decision.url_hash, signature)
        if response.status_code in _PUSHBACK_STATUSES:
            self._record_pushback(source.code, response.status_code)
        else:
            self._redis.delete(_FAILURES_KEY + source.code)
        return response

    def _handle_challenge(self, source_code: str, url_hash: str, signature: str) -> None:
        """A challenge was presented: record, disable, mark the run blocked, raise.

        Never solved, never bypassed, never outsourced — the only response to a
        CAPTCHA is to stop (CLAUDE.md guardrail).
        """
        self._decide(
            allowed=False,
            rule="captcha",
            outcome=PolicyDecisionOutcome.DENIED_CAPTCHA,
            reason=f"response matched challenge signature {signature!r}; source disabled",
            url_hash=url_hash,
            source_code=source_code,
        )
        self._disable_source(source_code, reason=f"captcha:{signature}")
        if self._mark_run_blocked is not None:
            self._mark_run_blocked(source_code, CaptchaDetected.error_class)
        _log.error(
            "policy_source_blocked_by_challenge",
            source=source_code,
            signature=signature,
            cooling_off_s=self._cooling_off_s,
        )
        raise CaptchaDetected(source_code, signature)

    def _record_pushback(self, source_code: str, status_code: int) -> None:
        failures = int(self._redis.incr(_FAILURES_KEY + source_code))
        self._redis.expire(_FAILURES_KEY + source_code, 3600)
        _log.warning(
            "policy_source_pushback",
            source=source_code,
            status=status_code,
            consecutive_failures=failures,
        )
        if failures >= self._failures_to_disable:
            self._redis.delete(_FAILURES_KEY + source_code)
            self._disable_source(source_code, reason=f"http_{status_code}_x{failures}")
            _log.error(
                "policy_source_disabled",
                source=source_code,
                reason=f"{failures} consecutive pushback responses (last was {status_code})",
                cooling_off_s=self._cooling_off_s,
            )

    def _disable_source(self, source_code: str, *, reason: str) -> None:
        self._redis.set(_COOLOFF_KEY + source_code, reason, ex=int(self._cooling_off_s))

    # ------------------------------------------------------------- helpers ----

    def _decide(
        self,
        *,
        allowed: bool,
        rule: str,
        outcome: PolicyDecisionOutcome,
        reason: str,
        url_hash: str,
        source_code: str | None,
        retry_after_s: float | None = None,
    ) -> Decision:
        decision = Decision(
            allowed=allowed,
            reason=reason,
            rule=rule,
            outcome=outcome,
            url_hash=url_hash,
            source_code=source_code,
            retry_after_s=retry_after_s,
        )
        self._decision_log.record(decision)
        return decision

    def _match_source(self, host: str) -> SourceEntry | None:
        for source in self._sources:
            domain = source.domain.lower()
            if host == domain or host.endswith("." + domain):
                return source
        return None

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self._clock(), tz=UTC)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PolicyEngine:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def load_policy_engine(
    *,
    redis_client: redis.Redis,
    decision_log: DecisionLog,
    user_agent: str,
    config_dir: Path | None = None,
    **kwargs: Any,
) -> PolicyEngine:
    """Build an engine from ``config/sources.yaml``, validating it on the way in.

    A file that fails its schema, or a validated file whose enabled sources are not
    currently collectable, is a startup failure — never a warning.
    """
    directory = config_dir if config_dir is not None else find_config_dir()
    config = load_config(directory / "sources.yaml", SourcesConfig)
    return PolicyEngine(
        config=config,
        redis_client=redis_client,
        decision_log=decision_log,
        user_agent=user_agent,
        **kwargs,
    )


__all__ = ["PolicyEngine", "load_policy_engine"]
