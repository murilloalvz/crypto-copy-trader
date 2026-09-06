from __future__ import annotations

from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class ProviderStartPacerSnapshotV44:
    interval_ms: int
    starts: int
    waited_starts: int
    total_wait_seconds: float
    max_wait_seconds: float


class ProviderStartPacerV44:
    """Thread-safe start pacer for off-path provider captures.

    This is intentionally not a retry mechanism. Each caller receives one start slot, sleeps before
    its original at-most-once capture, and then executes the unchanged provider probe. The pacer
    therefore reduces burst concurrency without replacing failed evidence with a later retry.
    """

    def __init__(self, *, interval_ms: int) -> None:
        if interval_ms < 0:
            raise ValueError("interval_ms cannot be negative")
        self.interval_ms = int(interval_ms)
        self._interval_seconds = self.interval_ms / 1000.0
        self._lock = threading.Lock()
        self._next_start_monotonic = 0.0
        self._starts = 0
        self._waited_starts = 0
        self._total_wait_seconds = 0.0
        self._max_wait_seconds = 0.0

    def wait_for_slot(self) -> float:
        now = time.monotonic()
        with self._lock:
            scheduled = max(now, self._next_start_monotonic)
            wait_seconds = max(0.0, scheduled - now)
            self._next_start_monotonic = scheduled + self._interval_seconds
            self._starts += 1
            if wait_seconds > 0.0005:
                self._waited_starts += 1
                self._total_wait_seconds += wait_seconds
                self._max_wait_seconds = max(self._max_wait_seconds, wait_seconds)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        return wait_seconds

    def snapshot(self) -> ProviderStartPacerSnapshotV44:
        with self._lock:
            return ProviderStartPacerSnapshotV44(
                interval_ms=self.interval_ms,
                starts=self._starts,
                waited_starts=self._waited_starts,
                total_wait_seconds=self._total_wait_seconds,
                max_wait_seconds=self._max_wait_seconds,
            )
