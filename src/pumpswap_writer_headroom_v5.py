from __future__ import annotations

from dataclasses import dataclass
import threading

from src.pumpswap_writer_pressure_v4 import (
    InstrumentedPumpSwapSQLiteWriterV4,
    PumpSwapWriterPressureSnapshotV4,
)


def _percentile(values: tuple[float, ...] | tuple[int, ...], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile)))
    return float(ordered[index])


@dataclass(frozen=True)
class PumpSwapWriterHeadroomSnapshotV5:
    base: PumpSwapWriterPressureSnapshotV4
    queue_depth_samples: tuple[int, ...]
    queue_depth_p50: float
    queue_depth_p95: float
    queue_wait_seconds: tuple[float, ...]
    queue_wait_p95_seconds: float
    result_wait_seconds: tuple[float, ...]
    result_wait_p95_seconds: float
    batch_service_seconds: tuple[float, ...]
    batch_service_p95_seconds: float


class InstrumentedPumpSwapSQLiteWriterV5(InstrumentedPumpSwapSQLiteWriterV4):
    """V4 writer telemetry plus sustained queue and wait headroom.

    V4 used queue high-water as its promotion warning. High-water is useful diagnostically but one
    transient burst can reach a large fraction of the worker reservoir while the writer still drains
    cleanly. V5 records queue depth at every submission and the actual per-request queue/result wait
    emitted by the authoritative writer. Promotion can therefore distinguish sustained pressure from
    a harmless one-off spike without changing writer batching or SQLite behavior.
    """

    last_instance: "InstrumentedPumpSwapSQLiteWriterV5 | None" = None

    def __init__(self, *args, telemetry_sink=None, **kwargs) -> None:
        self._v5_writer_lock = threading.Lock()
        self._v5_queue_depth_samples: list[int] = []
        self._v5_queue_wait_seconds: list[float] = []
        self._v5_result_wait_seconds: list[float] = []
        self._v5_batch_service_seconds: list[float] = []
        user_sink = telemetry_sink

        def v5_sink(item) -> None:
            with self._v5_writer_lock:
                self._v5_queue_wait_seconds.append(
                    max(0.0, float(item.writer_queue_wait_seconds))
                )
                self._v5_result_wait_seconds.append(
                    max(0.0, float(item.writer_result_wait_seconds))
                )
                self._v5_batch_service_seconds.append(
                    max(0.0, float(item.writer_batch_service_seconds))
                )
            if user_sink is not None:
                user_sink(item)

        super().__init__(*args, telemetry_sink=v5_sink, **kwargs)
        InstrumentedPumpSwapSQLiteWriterV5.last_instance = self

    def enqueue(self, prepared):
        future = super().enqueue(prepared)
        depth = int(self.queue_size)
        with self._v5_writer_lock:
            self._v5_queue_depth_samples.append(depth)
        return future

    def headroom_snapshot_v5(self) -> PumpSwapWriterHeadroomSnapshotV5:
        base = self.pressure_snapshot_v4()
        with self._v5_writer_lock:
            depths = tuple(self._v5_queue_depth_samples)
            queue_waits = tuple(self._v5_queue_wait_seconds)
            result_waits = tuple(self._v5_result_wait_seconds)
            batch_service = tuple(self._v5_batch_service_seconds)
        return PumpSwapWriterHeadroomSnapshotV5(
            base=base,
            queue_depth_samples=depths,
            queue_depth_p50=_percentile(depths, 0.50),
            queue_depth_p95=_percentile(depths, 0.95),
            queue_wait_seconds=queue_waits,
            queue_wait_p95_seconds=_percentile(queue_waits, 0.95),
            result_wait_seconds=result_waits,
            result_wait_p95_seconds=_percentile(result_waits, 0.95),
            batch_service_seconds=batch_service,
            batch_service_p95_seconds=_percentile(batch_service, 0.95),
        )
