from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import queue
import threading
import time

from src.pumpswap_hedged_batched_resolver_v33 import HedgedBatchedBoundedResolverV33


@dataclass(frozen=True)
class ParallelBatchHydrationSnapshot:
    batch_workers: int
    dispatched_batches: int
    dispatched_items: int
    inflight_high_water: int
    queue_depth_high_water: int
    batch_sizes: tuple[int, ...]
    batch_service_seconds: tuple[float, ...]


class ParallelHedgedBatchedBoundedResolverV41(HedgedBatchedBoundedResolverV33):
    """Use the already-budgeted PumpSwap resolution concurrency for multiple RPC batches.

    v32/v33 introduced causal batching and endpoint hedging, but one daemon batch thread still
    executed ``_fetch_batch`` synchronously. That meant exactly one ``getMultipleAccounts`` batch
    could be in flight at a time. Under an unknown-pool burst, the outer 18-resolution semaphore
    therefore did not translate into network-stage concurrency: small batches serialized behind one
    RPC and created a global normalization/reservation sequence hole.

    v41 keeps every existing cache, run-store, historical-store, per-pool single-flight, hydration
    budget, causal ``as_of`` and reservation/FIFO rule. Only the internal batch transport changes:

    * one dispatcher still forms batches in queue order;
    * up to ``hydration_batch_workers`` batches may execute concurrently;
    * each batch retains v33's first-valid hedged endpoint semantics;
    * ``batch_workers * hedge_endpoints`` may not exceed the pre-existing
      ``max_concurrent_resolutions`` budget, so this does not silently increase the configured
      expensive-work ceiling;
    * when all batch workers are busy, the queue accumulates and the next dispatch drains additional
      waiting pools into the same batch instead of creating one RPC per pool.
    """

    last_instance: "ParallelHedgedBatchedBoundedResolverV41 | None" = None

    def __init__(
        self,
        *args,
        hydration_batch_workers: int = 8,
        hedge_endpoints: int = 2,
        **kwargs,
    ) -> None:
        if hydration_batch_workers <= 0:
            raise ValueError("hydration_batch_workers must be positive")
        if hedge_endpoints <= 0:
            raise ValueError("hedge_endpoints must be positive")
        resolution_budget = int(kwargs.get("max_concurrent_resolutions", 0) or 0)
        if resolution_budget > 0 and hydration_batch_workers * hedge_endpoints > resolution_budget:
            raise ValueError(
                "hydration_batch_workers * hedge_endpoints must not exceed "
                "max_concurrent_resolutions"
            )

        self.hydration_batch_workers = int(hydration_batch_workers)
        self._parallel_batch_slots = threading.Semaphore(self.hydration_batch_workers)
        self._parallel_batch_executor = ThreadPoolExecutor(
            max_workers=self.hydration_batch_workers,
            thread_name_prefix="pumpswap-hydration-batch-v41",
        )
        self._parallel_metrics_lock = threading.Lock()
        self._parallel_inflight = 0
        self._parallel_dispatched_batches = 0
        self._parallel_dispatched_items = 0
        self._parallel_inflight_high_water = 0
        self._parallel_queue_depth_high_water = 0
        self._parallel_batch_sizes: list[int] = []
        self._parallel_batch_service_seconds: list[float] = []

        super().__init__(*args, hedge_endpoints=hedge_endpoints, **kwargs)
        ParallelHedgedBatchedBoundedResolverV41.last_instance = self
        type(self).last_instance = self

    def _finish_parallel_batch(
        self,
        future: Future,
        *,
        items,
        started_monotonic: float,
    ) -> None:
        try:
            future.result()
        except BaseException as exc:
            # v33 normally converts endpoint failures into per-item Future exceptions. Preserve
            # explicit failure even if an unexpected exception escapes the batch method itself.
            for _, item_future in items:
                if not item_future.done():
                    item_future.set_exception(exc)
        finally:
            service = max(0.0, time.monotonic() - started_monotonic)
            with self._parallel_metrics_lock:
                self._parallel_inflight = max(0, self._parallel_inflight - 1)
                self._parallel_batch_service_seconds.append(service)
            for _ in items:
                self._batch_queue.task_done()
            self._parallel_batch_slots.release()

    def _batch_loop(self) -> None:
        """Form ordered batches but execute multiple batches concurrently within the fixed budget."""

        max_wait = self.hydration_batch_max_wait_ms / 1000.0
        while True:
            first = self._batch_queue.get()
            items = [first]
            collect_started = time.monotonic()
            while len(items) < self.hydration_batch_size:
                remaining = max_wait - (time.monotonic() - collect_started)
                if remaining <= 0:
                    break
                try:
                    items.append(self._batch_queue.get(timeout=remaining))
                except queue.Empty:
                    break

            # If all network lanes are busy, wait here while new pool misses accumulate in the
            # shared queue. Once a lane opens, drain that accumulated work into this same dispatch.
            self._parallel_batch_slots.acquire()
            while len(items) < self.hydration_batch_size:
                try:
                    items.append(self._batch_queue.get_nowait())
                except queue.Empty:
                    break

            started = time.monotonic()
            with self._parallel_metrics_lock:
                self._parallel_inflight += 1
                self._parallel_dispatched_batches += 1
                self._parallel_dispatched_items += len(items)
                self._parallel_inflight_high_water = max(
                    self._parallel_inflight_high_water,
                    self._parallel_inflight,
                )
                self._parallel_queue_depth_high_water = max(
                    self._parallel_queue_depth_high_water,
                    self._batch_queue.qsize(),
                )
                self._parallel_batch_sizes.append(len(items))

            try:
                submitted = self._parallel_batch_executor.submit(self._fetch_batch, items)
            except BaseException as exc:
                for _, item_future in items:
                    if not item_future.done():
                        item_future.set_exception(exc)
                with self._parallel_metrics_lock:
                    self._parallel_inflight = max(0, self._parallel_inflight - 1)
                    self._parallel_batch_service_seconds.append(0.0)
                for _ in items:
                    self._batch_queue.task_done()
                self._parallel_batch_slots.release()
                continue

            submitted.add_done_callback(
                lambda future, batch=tuple(items), began=started: self._finish_parallel_batch(
                    future,
                    items=batch,
                    started_monotonic=began,
                )
            )

    def parallel_batch_snapshot(self) -> ParallelBatchHydrationSnapshot:
        with self._parallel_metrics_lock:
            return ParallelBatchHydrationSnapshot(
                batch_workers=self.hydration_batch_workers,
                dispatched_batches=self._parallel_dispatched_batches,
                dispatched_items=self._parallel_dispatched_items,
                inflight_high_water=self._parallel_inflight_high_water,
                queue_depth_high_water=self._parallel_queue_depth_high_water,
                batch_sizes=tuple(self._parallel_batch_sizes),
                batch_service_seconds=tuple(self._parallel_batch_service_seconds),
            )

    def shutdown_parallel_batches(self, *, wait: bool = False) -> None:
        """Release executor resources after a bounded smoke has stopped submitting new misses."""

        self._parallel_batch_executor.shutdown(wait=wait, cancel_futures=False)
