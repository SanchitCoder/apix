"""Session rotation.

Real proxy egress (``APIX_PROXY_*`` in ``apix_core.settings``) is out of scope for the
fixture-replay phase this package implements. What is in scope, and cheap, is not
presenting every request from one route as part of one uninterrupted session: this
cycles a small pool of independent session identities so a spider's own traffic
pattern does not look like a single relentless client even before a proxy pool exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class SessionContext:
    """One identity in the rotation. ``headers`` are merged into every request."""

    session_id: str
    headers: MappingProxyType[str, str]


class SessionRotator:
    """Round-robins through ``pool_size`` session identities."""

    def __init__(self, pool_size: int = 4) -> None:
        if pool_size < 1:
            raise ValueError("pool_size must be >= 1")
        self._pool = [f"apix-session-{i:02d}" for i in range(pool_size)]
        self._next_index = 0

    def next(self) -> SessionContext:
        session_id = self._pool[self._next_index % len(self._pool)]
        self._next_index += 1
        return SessionContext(
            session_id=session_id,
            headers=MappingProxyType({"X-APIx-Session": session_id}),
        )


__all__ = ["SessionContext", "SessionRotator"]
