"""Shared types for acquisition strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from apix_collector.session import SessionContext
    from apix_core.models.enums import CollectionMethod
    from apix_core.policy import PolicyEngine
    from apix_core.provenance.stamp import RawResponse


@dataclass(frozen=True, slots=True)
class SimpleResponse:
    """A minimal :class:`~apix_core.provenance.stamp.RawResponse`.

    ``httpx.Response`` satisfies the protocol structurally already; this exists for
    strategies (:class:`~apix_collector.strategies.rendered_page.RenderedPageStrategy`)
    that never construct one, so ``apix_collector`` still never has to import an HTTP
    client to produce something ``apix_core.provenance.stamp.stamp`` can consume.
    """

    url: str
    content: bytes


@dataclass(frozen=True, slots=True)
class FetchedPayload:
    """The result of one successful acquisition attempt."""

    body: bytes
    response: RawResponse
    collection_method: CollectionMethod


class AcquisitionStrategy(Protocol):
    """Fetches one URL and reports how it was fetched.

    ``name`` is the :class:`~apix_core.models.enums.CollectionMethod` this strategy
    represents when it is used against a live source. ``apix_collector.run`` may
    override it uniformly to ``FIXTURE`` when the whole run is a fixture replay —
    a strategy always reports its own genuine acquisition mechanism, never a guess
    about what mode it is running in.
    """

    @property
    def name(self) -> CollectionMethod: ...

    def fetch(
        self,
        *,
        policy_engine: PolicyEngine,
        url: str,
        session: SessionContext,
    ) -> FetchedPayload:
        """Fetch ``url``. Raises :class:`apix_collector.errors.FetchFailed` on a
        non-success acquisition, or lets ``PolicyDenied``/``CaptchaDetected`` from
        ``apix_core.policy`` propagate unchanged — those are never retried."""
        ...


__all__ = ["AcquisitionStrategy", "FetchedPayload", "SimpleResponse"]
