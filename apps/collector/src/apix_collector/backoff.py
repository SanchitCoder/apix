"""Jittered exponential backoff for retryable fetch failures.

``sleep`` and ``rng`` are injectable so tests exercise real retry logic without a real
clock — the no-live-internet rule for tests extends to not-actually-waiting either.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable


class Backoff:
    """Computes the delay before retry attempt ``n`` (0-indexed)."""

    def __init__(
        self,
        *,
        base_s: float = 0.5,
        max_s: float = 8.0,
        jitter_low: float = 0.5,
        jitter_high: float = 1.5,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        if base_s <= 0 or max_s <= 0:
            raise ValueError("base_s and max_s must be positive")
        self._base_s = base_s
        self._max_s = max_s
        self._jitter_low = jitter_low
        self._jitter_high = jitter_high
        self._sleep = sleep
        self._rng = rng or random.Random()  # noqa: S311 — retry jitter, not a security control

    def delay_s(self, attempt: int) -> float:
        raw = min(self._max_s, self._base_s * (2**attempt))
        return float(raw * self._rng.uniform(self._jitter_low, self._jitter_high))

    def wait(self, attempt: int) -> None:
        self._sleep(self.delay_s(attempt))


__all__ = ["Backoff"]
