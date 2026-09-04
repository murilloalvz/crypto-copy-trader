import asyncio
from concurrent.futures import Future
import queue
import threading
import time
from typing import Callable

from src.pumpswap_normalized_persistence import PumpSwapNormalizedPersistResult
from src.pumpswap_normalized_persistence_v3 import (
    PreparedPumpSwapPersistenceV3,
    PumpSwapPersistenceV3Telemetry,
    _persist_prepared_batch_db_stage,
    prepare_pumpswap_notification_normalized_v3,
)
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapPoolResolver


_SENTINEL = object()


class PumpSwapSQLiteThreadedMicrobatchWriter:
    """Own the whole PumpSwap SQLite microbatch loop in one dedicated OS thread.

    v16 kept batch collection in an asyncio task and moved only the SQLite call into an
    executor. Under burst load that task itself could be starved by the event loop. This
    writer uses a standard thread-safe queue and performs batch collection plus the DB
    transaction on the same dedicated thread. Async callers only enqueue a request and
    await a concurrent Future bridged back to their loop.
    """

    def __init__(
        self,
        *,
        batch_size: int = 32,
        max_wait_ms: int = 10,
        telemetry_sink: Callable[[PumpSwapPersistenceV3Telemetry], None] | None = None,
    ):
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if max_wait_ms < 0:
            raise ValueError("max_wait_ms cannot be negative")
        self.batch_size = int(batch_size)
        self.max_wait_seconds = float(max_wait_ms) / 1000.0
        self.telemetry_sink = telemetry_sink
        self.batch_sizes: list[int] = []
        self.batch_service_seconds: list[float] = []
        self._queue: queue.Queue = queue.Queue()
        self._closing = False
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run,
            name="pumpswap-sqlite-threaded-microbatch-writer",
            daemon=True,
        )
        self._thread.start()

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def enqueue(
        self,
        prepared: PreparedPumpSwapPersistenceV3,
    ) -> Future:
        with self._lock:
            if self._closing:
                raise RuntimeError("PumpSwap SQLite threaded writer is closing")
            future: Future = Future()
            self._queue.put_nowait(
                (prepared, time.perf_counter(), future)
            )
            return future

    async def submit(
        self,
        prepared: PreparedPumpSwapPersistenceV3,
    ) -> PumpSwapNormalizedPersistResult:
        future = self.enqueue(prepared)
        return await asyncio.wrap_future(future)

    async def close(self, *, cancel_pending: bool = True) -> None:
        with self._lock:
            if self._closing:
                already_closing = True
            else:
                self._closing = True
                already_closing = False
        if already_closing:
            if self._thread.is_alive():
                await asyncio.to_thread(self._thread.join)
            return

        if cancel_pending:
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is _SENTINEL:
                    self._queue.task_done()
                    continue
                _, _, future = item
                future.cancel()
                self._queue.task_done()

        self._queue.put_nowait(_SENTINEL)
        if self._thread.is_alive():
            await asyncio.to_thread(self._thread.join)

    def _run(self) -> None:
        stop_after_batch = False
        while True:
            first = self._queue.get()
            if first is _SENTINEL:
                self._queue.task_done()
                break

            batch = [first]
            collect_started = time.perf_counter()
            stop_after_batch = False
            while len(batch) < self.batch_size:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    remaining = self.max_wait_seconds - (
                        time.perf_counter() - collect_started
                    )
                    if remaining <= 0:
                        break
                    try:
                        item = self._queue.get(timeout=remaining)
                    except queue.Empty:
                        break

                if item is _SENTINEL:
                    self._queue.task_done()
                    stop_after_batch = True
                    break
                batch.append(item)

            try:
                prepared_items = tuple(item[0] for item in batch)
                results, writer_started, writer_finished = _persist_prepared_batch_db_stage(
                    prepared_items
                )
                if len(results) != len(batch):
                    raise RuntimeError(
                        "PumpSwap threaded writer batch result count does not match input count"
                    )
                batch_service = max(0.0, writer_finished - writer_started)
                self.batch_sizes.append(len(batch))
                self.batch_service_seconds.append(batch_service)
                for request, result in zip(batch, results):
                    prepared, submitted_perf_counter, future = request
                    if self.telemetry_sink is not None:
                        self.telemetry_sink(
                            PumpSwapPersistenceV3Telemetry(
                                resolver_and_normalize_seconds=(
                                    prepared.resolver_and_normalize_seconds
                                ),
                                writer_queue_wait_seconds=max(
                                    0.0,
                                    writer_started - submitted_perf_counter,
                                ),
                                writer_batch_service_seconds=batch_service,
                                writer_result_wait_seconds=max(
                                    0.0,
                                    writer_finished - submitted_perf_counter,
                                ),
                                writer_batch_size=len(batch),
                            )
                        )
                    if not future.done():
                        future.set_result(result)
            except Exception as exc:
                for _, _, future in batch:
                    if not future.done():
                        future.set_exception(exc)
            finally:
                for _ in batch:
                    self._queue.task_done()

            if stop_after_batch:
                break


async def persist_pumpswap_notification_normalized_v4(
    notification: PumpSwapLogNotification,
    *,
    acquisition_run_key: str,
    resolver: PumpSwapPoolResolver,
    writer: PumpSwapSQLiteThreadedMicrobatchWriter,
) -> PumpSwapNormalizedPersistResult:
    prepared = await prepare_pumpswap_notification_normalized_v3(
        notification,
        acquisition_run_key=acquisition_run_key,
        resolver=resolver,
    )
    return await writer.submit(prepared)
