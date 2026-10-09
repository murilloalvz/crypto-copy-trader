from __future__ import annotations

from dataclasses import dataclass
import threading

from src.pumpswap_normalized_persistence_v4 import PumpSwapSQLiteThreadedMicrobatchWriter


@dataclass(frozen=True)
class PumpSwapWriterPressureSnapshotV4:
    submitted: int
    completed: int
    pending_at_close: int
    queue_high_water: int
    queue_before_close: int
    batch_count: int
    average_batch_size: float
    max_batch_size: int
    configured_batch_size: int
    batch_fill_pct: float


class InstrumentedPumpSwapSQLiteWriterV4(PumpSwapSQLiteThreadedMicrobatchWriter):
    """Observation-only writer wrapper used by the v4 systems profile.

    It does not change batching or SQLite behavior. It records whether the single authoritative
    PumpSwap writer is accumulating work faster than it completes it, plus how effectively the
    configured microbatch capacity is being used.
    """

    last_instance: "InstrumentedPumpSwapSQLiteWriterV4 | None" = None

    def __init__(self, *args, telemetry_sink=None, **kwargs) -> None:
        self._v4_metrics_lock = threading.Lock()
        self._v4_submitted = 0
        self._v4_completed = 0
        self._v4_queue_high_water = 0
        self._v4_queue_before_close = 0
        user_sink = telemetry_sink

        def traced_sink(item) -> None:
            with self._v4_metrics_lock:
                self._v4_completed += 1
            if user_sink is not None:
                user_sink(item)

        super().__init__(*args, telemetry_sink=traced_sink, **kwargs)
        InstrumentedPumpSwapSQLiteWriterV4.last_instance = self

    def enqueue(self, prepared):
        future = super().enqueue(prepared)
        queue_size = self.queue_size
        with self._v4_metrics_lock:
            self._v4_submitted += 1
            self._v4_queue_high_water = max(self._v4_queue_high_water, queue_size)
        return future

    async def close(self, *, cancel_pending: bool = True) -> None:
        with self._v4_metrics_lock:
            self._v4_queue_before_close = self.queue_size
        await super().close(cancel_pending=cancel_pending)

    def pressure_snapshot_v4(self) -> PumpSwapWriterPressureSnapshotV4:
        with self._v4_metrics_lock:
            submitted = int(self._v4_submitted)
            completed = int(self._v4_completed)
            queue_high_water = int(self._v4_queue_high_water)
            queue_before_close = int(self._v4_queue_before_close)
        batch_sizes = tuple(int(value) for value in self.batch_sizes)
        batch_count = len(batch_sizes)
        average_batch_size = (
            sum(batch_sizes) / batch_count if batch_count else 0.0
        )
        configured = int(self.batch_size)
        fill_pct = (
            100.0 * average_batch_size / configured if configured > 0 else 0.0
        )
        return PumpSwapWriterPressureSnapshotV4(
            submitted=submitted,
            completed=completed,
            pending_at_close=max(0, submitted - completed),
            queue_high_water=queue_high_water,
            queue_before_close=queue_before_close,
            batch_count=batch_count,
            average_batch_size=average_batch_size,
            max_batch_size=max(batch_sizes, default=0),
            configured_batch_size=configured,
            batch_fill_pct=fill_pct,
        )
