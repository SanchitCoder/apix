"""``BaseSpider``: the contract every source spider implements.

Given ``(route_code, travel_date, advance_days)``, a spider yields ``RawQuote``
objects. Everything a spider needs to do that safely and politely is handled here,
once, so a concrete spider (``apix_collector.spiders.indigo`` and friends) only has to
say which strategies it tries, in what order, and how to build a URL for each one:

* retries with jittered exponential backoff, only for the failures worth retrying;
* falling back from one acquisition strategy to the next;
* session rotation, so retries and fallbacks are not all the same client session;
* a per-run request budget it cannot exceed.

A spider never talks to the database and never decides what a failure means for the
collection run — it raises, and ``apix_collector.run`` decides what row that becomes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, ClassVar

from apix_collector.backoff import Backoff
from apix_collector.budget import RunBudget
from apix_collector.errors import AllStrategiesFailed, FetchFailed
from apix_collector.quote import MapperContext
from apix_collector.session import SessionRotator

if TYPE_CHECKING:
    from collections.abc import Sequence

    from apix_collector.mapper import Mapper
    from apix_collector.quote import RawQuote
    from apix_collector.strategies.base import AcquisitionStrategy, FetchedPayload
    from apix_core.models.enums import CollectionMethod
    from apix_core.policy import PolicyEngine

#: HTTP-ish statuses worth a retry of the *same* strategy before falling back to the
#: next one. 403/404/401 and the like mean "this will not work no matter how many
#: times we ask" — falling back (or giving up) is the only useful response.
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class CollectionOutcome:
    """Everything ``apix_collector.run`` needs to persist one successful collection."""

    quotes: list[RawQuote]
    payload: FetchedPayload
    strategy_name: CollectionMethod
    route_code: str
    travel_date: date
    query_date: date
    advance_days: int


class BaseSpider(ABC):
    """One source's collection logic. Concrete spiders declare strategies and URLs."""

    #: The ``source.code`` this spider collects for — matches an entry in
    #: ``config/sources.yaml`` and the seeded ``source`` table.
    source_code: ClassVar[str]

    def __init__(
        self,
        *,
        mapper: Mapper,
        strategies: Sequence[AcquisitionStrategy],
        policy_engine: PolicyEngine,
        budget: RunBudget | None = None,
        max_requests_per_run: int = 20,
        retries: int = 2,
        session_rotator: SessionRotator | None = None,
        backoff: Backoff | None = None,
    ) -> None:
        if not strategies:
            raise ValueError(f"{self.source_code}: a spider needs at least one strategy")
        self._mapper = mapper
        self._strategies = tuple(strategies)
        self._policy_engine = policy_engine
        self._budget = budget or RunBudget(self.source_code, max_requests_per_run)
        self._retries = retries
        self._session_rotator = session_rotator or SessionRotator()
        self._backoff = backoff or Backoff()

    @property
    def budget(self) -> RunBudget:
        return self._budget

    @abstractmethod
    def build_url(
        self,
        strategy: AcquisitionStrategy,
        *,
        route_code: str,
        travel_date: date,
        query_date: date,
    ) -> str:
        """The URL ``strategy`` should fetch for this route and date pair."""

    def collect(
        self, *, route_code: str, travel_date: date, advance_days: int
    ) -> CollectionOutcome:
        """Collect quotes for one route/date/advance-window combination.

        Tries each declared strategy in order; the first one to succeed wins — later
        strategies are never also tried once quotes have been produced. Raises
        :class:`~apix_collector.errors.AllStrategiesFailed` if none does, or lets a
        policy denial, a CAPTCHA, or a schema-drift error from the mapper propagate:
        those are decisions for the caller, not failures for this spider to absorb.
        """
        if advance_days < 0 or advance_days > 365:
            raise ValueError(f"advance_days must be between 0 and 365, got {advance_days}")
        query_date = travel_date - timedelta(days=advance_days)
        context = MapperContext(
            route_code=route_code, travel_date=travel_date, query_date=query_date
        )

        attempts: list[str] = []
        for strategy in self._strategies:
            url = self.build_url(
                strategy, route_code=route_code, travel_date=travel_date, query_date=query_date
            )
            try:
                payload = self._fetch_with_retry(strategy, url)
            except FetchFailed as exc:
                attempts.append(f"{strategy.name.value}: {exc}")
                continue
            quotes = self._mapper.parse(payload.body, context)
            return CollectionOutcome(
                quotes=quotes,
                payload=payload,
                strategy_name=strategy.name,
                route_code=route_code,
                travel_date=travel_date,
                query_date=query_date,
                advance_days=advance_days,
            )
        raise AllStrategiesFailed(self.source_code, route_code, attempts)

    def _fetch_with_retry(self, strategy: AcquisitionStrategy, url: str) -> FetchedPayload:
        last_exc: FetchFailed | None = None
        for attempt in range(self._retries + 1):
            self._budget.reserve(1)
            session = self._session_rotator.next()
            try:
                return strategy.fetch(policy_engine=self._policy_engine, url=url, session=session)
            except FetchFailed as exc:
                last_exc = exc
                if exc.status_code not in RETRYABLE_STATUS_CODES or attempt == self._retries:
                    raise
                self._backoff.wait(attempt)
        assert last_exc is not None  # loop always returns or raises
        raise last_exc


__all__ = ["RETRYABLE_STATUS_CODES", "BaseSpider", "CollectionOutcome"]
