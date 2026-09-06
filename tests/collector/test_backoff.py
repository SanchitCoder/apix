from __future__ import annotations

import random

from apix_collector.backoff import Backoff


def test_delay_grows_exponentially_and_is_capped() -> None:
    backoff = Backoff(base_s=1.0, max_s=4.0, jitter_low=1.0, jitter_high=1.0)  # no jitter
    assert backoff.delay_s(0) == 1.0
    assert backoff.delay_s(1) == 2.0
    assert backoff.delay_s(2) == 4.0
    assert backoff.delay_s(5) == 4.0  # capped


def test_jitter_stays_within_bounds() -> None:
    backoff = Backoff(
        base_s=1.0,
        max_s=100.0,
        jitter_low=0.5,
        jitter_high=1.5,
        rng=random.Random(0),  # noqa: S311
    )
    for attempt in range(5):
        delay = backoff.delay_s(attempt)
        raw = min(100.0, 1.0 * (2**attempt))
        assert 0.5 * raw <= delay <= 1.5 * raw


def test_wait_calls_the_injected_sleep() -> None:
    calls: list[float] = []
    backoff = Backoff(sleep=calls.append, rng=random.Random(0))  # noqa: S311
    backoff.wait(0)
    assert len(calls) == 1
    assert calls[0] > 0
