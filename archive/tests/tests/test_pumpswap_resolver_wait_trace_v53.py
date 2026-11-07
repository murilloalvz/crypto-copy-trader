from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.pumpswap_resolver_wait_trace_v53 import TracedDeadlineBoundedResolverV53


class ResolverWaitTraceV53Tests(unittest.IsolatedAsyncioTestCase):
    def _resolver(self, *, capacity: int = 1):
        return TracedDeadlineBoundedResolverV53(
            acquisition_run_key="run-v53",
            commitment="confirmed",
            client=SimpleNamespace(
                timeout=0.05,
                rpc_urls=["https://first.invalid", "https://second.invalid"],
            ),
            max_network_hydrations=100,
            max_concurrent_resolutions=capacity,
            hydration_batch_size=64,
            hydration_batch_max_wait_ms=5,
            hedge_endpoints=1,
            hydration_batch_workers=1,
        )

    async def test_capacity_wait_is_observed_without_replacing_parent_resolve(self):
        resolver = self._resolver(capacity=1)

        async def fake_parent(_self, pool_address: str, *, as_of: int):
            return None

        await resolver._resolution_semaphore.acquire()
        try:
            with patch(
                "src.pumpswap_concurrent_resolver.ReusablePumpSwapPoolResolver.resolve",
                new=fake_parent,
            ):
                task = asyncio.create_task(resolver.resolve("POOL", as_of=100))
                await asyncio.sleep(0.02)
                self.assertFalse(task.done())
                resolver._resolution_semaphore.release()
                await asyncio.wait_for(task, timeout=1)
        finally:
            if resolver._resolution_semaphore.locked():
                resolver._resolution_semaphore.release()
            resolver.shutdown_parallel_batches(wait=False)

        snapshot = resolver.resolver_wait_snapshot_v53()
        self.assertGreaterEqual(snapshot.capacity_waits, 1)
        self.assertTrue(snapshot.demand_capacity_wait_seconds)
        self.assertGreater(max(snapshot.demand_capacity_wait_seconds), 0.01)
        self.assertGreaterEqual(snapshot.demand_capacity_waiters_high_water, 1)

    async def test_same_pool_lock_wait_is_observed(self):
        resolver = self._resolver(capacity=1)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def fake_parent(_self, pool_address: str, *, as_of: int):
            entered.set()
            await release.wait()
            return None

        with patch(
            "src.pumpswap_concurrent_resolver.ReusablePumpSwapPoolResolver.resolve",
            new=fake_parent,
        ):
            first = asyncio.create_task(resolver.resolve("POOL", as_of=100))
            await entered.wait()
            second = asyncio.create_task(resolver.resolve("POOL", as_of=100))
            await asyncio.sleep(0.02)
            self.assertFalse(second.done())
            release.set()
            await asyncio.gather(first, second)

        snapshot = resolver.resolver_wait_snapshot_v53()
        resolver.shutdown_parallel_batches(wait=False)
        self.assertGreaterEqual(snapshot.pool_lock_waits, 1)
        self.assertTrue(snapshot.demand_pool_lock_wait_seconds)
        self.assertGreater(max(snapshot.demand_pool_lock_wait_seconds), 0.01)
        self.assertTrue(snapshot.hot_pool_lock_wait_seconds)
        self.assertEqual(snapshot.hot_pool_lock_wait_seconds[0][0], "POOL")

    async def test_prefetch_task_name_is_classified_separately(self):
        resolver = self._resolver(capacity=1)

        async def fake_parent(_self, pool_address: str, *, as_of: int):
            return None

        with patch(
            "src.pumpswap_concurrent_resolver.ReusablePumpSwapPoolResolver.resolve",
            new=fake_parent,
        ):
            task = asyncio.create_task(
                resolver.resolve("POOL", as_of=100),
                name="pumpswap-ingress-prefetch-v53:POOL",
            )
            await task

        snapshot = resolver.resolver_wait_snapshot_v53()
        resolver.shutdown_parallel_batches(wait=False)
        self.assertEqual(len(snapshot.prefetch_resolve_seconds), 1)
        self.assertEqual(len(snapshot.demand_resolve_seconds), 0)


if __name__ == "__main__":
    unittest.main()
