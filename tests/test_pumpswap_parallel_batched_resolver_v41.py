from __future__ import annotations

from concurrent.futures import Future
import threading
import time
import unittest

from src.pumpswap_parallel_batched_resolver_v41 import (
    ParallelHedgedBatchedBoundedResolverV41,
)


class _BootstrapClient:
    def __init__(self):
        self.timeout = 3
        self.rpc_urls = ["https://a.invalid", "https://b.invalid"]


class ParallelBatchedResolverV41Tests(unittest.TestCase):
    def _resolver(self, **overrides):
        kwargs = dict(
            acquisition_run_key="run",
            commitment="confirmed",
            client=_BootstrapClient(),
            max_network_hydrations=100,
            max_concurrent_resolutions=18,
            hydration_batch_size=4,
            hydration_batch_max_wait_ms=0,
            hedge_endpoints=2,
            hydration_batch_workers=4,
        )
        kwargs.update(overrides)
        return ParallelHedgedBatchedBoundedResolverV41(**kwargs)

    def test_parallel_endpoint_budget_cannot_exceed_existing_resolution_budget(self):
        with self.assertRaises(ValueError):
            self._resolver(hydration_batch_workers=10, hedge_endpoints=2)

    def test_multiple_batches_can_be_inflight_concurrently(self):
        resolver = self._resolver(hydration_batch_size=2, hydration_batch_workers=4)
        active = 0
        max_active = 0
        lock = threading.Lock()

        def fake_fetch(items):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.05)
                for pool, future in items:
                    if not future.done():
                        future.set_result(pool)
            finally:
                with lock:
                    active -= 1

        resolver._fetch_batch = fake_fetch
        futures: list[Future] = []
        for index in range(12):
            future = Future()
            futures.append(future)
            resolver._batch_queue.put((f"pool-{index}", future))

        results = [future.result(timeout=2.0) for future in futures]
        resolver._batch_queue.join()
        snapshot = resolver.parallel_batch_snapshot()
        resolver.shutdown_parallel_batches(wait=True)

        self.assertEqual(results, [f"pool-{index}" for index in range(12)])
        self.assertGreaterEqual(max_active, 2)
        self.assertGreaterEqual(snapshot.inflight_high_water, 2)
        self.assertEqual(snapshot.dispatched_items, 12)
        self.assertGreater(snapshot.dispatched_batches, 0)
        self.assertEqual(len(snapshot.batch_sizes), snapshot.dispatched_batches)
        self.assertEqual(len(snapshot.batch_service_seconds), snapshot.dispatched_batches)

    def test_busy_batch_lanes_keep_total_network_concurrency_bounded(self):
        resolver = self._resolver(
            hydration_batch_size=1,
            hydration_batch_workers=3,
            hedge_endpoints=2,
        )
        release = threading.Event()
        active = 0
        max_active = 0
        lock = threading.Lock()

        def fake_fetch(items):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            release.wait(timeout=1.0)
            for pool, future in items:
                if not future.done():
                    future.set_result(pool)
            with lock:
                active -= 1

        resolver._fetch_batch = fake_fetch
        futures: list[Future] = []
        for index in range(8):
            future = Future()
            futures.append(future)
            resolver._batch_queue.put((f"pool-{index}", future))

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            with lock:
                if max_active >= 3:
                    break
            time.sleep(0.01)
        release.set()
        for future in futures:
            future.result(timeout=2.0)
        resolver._batch_queue.join()
        snapshot = resolver.parallel_batch_snapshot()
        resolver.shutdown_parallel_batches(wait=True)

        self.assertLessEqual(max_active, 3)
        self.assertEqual(snapshot.inflight_high_water, 3)
        self.assertEqual(snapshot.dispatched_items, 8)


if __name__ == "__main__":
    unittest.main()
