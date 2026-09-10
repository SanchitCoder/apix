from __future__ import annotations

from datetime import UTC, datetime

from apix_core.watchdog.frequency import can_run_probe_now


class TestCanRunProbeNow:
    def test_never_run_before_is_always_permitted(self) -> None:
        assert can_run_probe_now(None, 12.0, datetime(2026, 9, 8, tzinfo=UTC)) is True

    def test_permitted_once_the_interval_has_elapsed(self) -> None:
        last = datetime(2026, 9, 8, 0, 0, tzinfo=UTC)
        now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
        assert can_run_probe_now(last, 12.0, now) is True

    def test_refused_before_the_interval_has_elapsed(self) -> None:
        last = datetime(2026, 9, 8, 0, 0, tzinfo=UTC)
        now = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
        assert can_run_probe_now(last, 12.0, now) is False
