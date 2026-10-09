from __future__ import annotations

import asyncio
import unittest

from src.pumpswap_opportunistic_prefetch_v53 import (
    OpportunisticPumpSwapIngressPrefetchV53,
)
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapTradeEvent


def _notification(pool: str = "POOL") -> PumpSwapLogNotification:
    return PumpSwapLogNotification(
        signature="sig",
        slot=1,
        observed_at=100,
        trade_events=(
            PumpSwapTradeEvent(
                side="buy",
                pool=pool,
                user="user",
                timestamp=99,
                base_amount_raw=1,
                quote_amount_raw=2,
                event_index=0,
            ),
        ),
    )


class _Resolver:
    def __init__(self, *, capacity: int = 1) -> None:
        self._resolution_semaphore = asyncio.Semaphore(capacity)
        self._pool_locks: dict[str, asyncio.Lock] = {}
        self.calls = 0
        self.cached = None

    def _causal_cache_hit(self, pool: str, *, as_of: int):
        return self.cached

    async def resolve(self, pool_address: str, *, as_of: int):
        self.calls += 1
        lock = self._pool_locks.setdefault(pool_address, asyncio.Lock())
        async with lock:
            async with self._resolution_semaphore:
                return object()


class OpportunisticPrefetchV53Tests(unittest.IsolatedAsyncioTestCase):
    async def test_saturated_capacity_skips_without_joining_resolver_queue(self):
        resolver = _Resolver(capacity=1)
        await resolver._resolution_semaphore.acquire()
        prefetch = OpportunisticPumpSwapIngressPrefetchV53()
        try:
            prefetch.schedule(_notification(), resolver)
            await prefetch.drain(timeout_seconds=1)
            await asyncio.sleep(0)
        finally:
            resolver._resolution_semaphore.release()

        snapshot = prefetch.snapshot_v53()
        self.assertEqual(resolver.calls, 0)
        self.assertEqual(snapshot.skipped_capacity, 1)
        self.assertEqual(snapshot.skipped_pool_busy, 0)
        self.assertEqual(snapshot.admitted, 0)
        self.assertEqual(snapshot.completed_unresolved, 0)
        self.assertEqual(snapshot.failed, 0)

    async def test_busy_same_pool_skips_without_waiting_for_lock(self):
        resolver = _Resolver(capacity=1)
        lock = asyncio.Lock()
        await lock.acquire()
        resolver._pool_locks["POOL"] = lock
        prefetch = OpportunisticPumpSwapIngressPrefetchV53()
        try:
            prefetch.schedule(_notification(), resolver)
            await prefetch.drain(timeout_seconds=1)
            await asyncio.sleep(0)
        finally:
            lock.release()

        snapshot = prefetch.snapshot_v53()
        self.assertEqual(resolver.calls, 0)
        self.assertEqual(snapshot.skipped_pool_busy, 1)
        self.assertEqual(snapshot.skipped_capacity, 0)
        self.assertEqual(snapshot.completed_unresolved, 0)

    async def test_free_capacity_admits_normal_prefetch(self):
        resolver = _Resolver(capacity=1)
        prefetch = OpportunisticPumpSwapIngressPrefetchV53()
        prefetch.schedule(_notification(), resolver)
        await prefetch.drain(timeout_seconds=1)
        await asyncio.sleep(0)

        snapshot = prefetch.snapshot_v53()
        self.assertEqual(resolver.calls, 1)
        self.assertEqual(snapshot.admitted, 1)
        self.assertEqual(snapshot.completed_available, 1)
        self.assertEqual(snapshot.skipped_capacity, 0)
        self.assertEqual(snapshot.skipped_pool_busy, 0)

    async def test_causal_cache_hit_is_preserved_even_when_capacity_is_full(self):
        resolver = _Resolver(capacity=1)
        resolver.cached = object()
        await resolver._resolution_semaphore.acquire()
        prefetch = OpportunisticPumpSwapIngressPrefetchV53()
        try:
            prefetch.schedule(_notification(), resolver)
            await prefetch.drain(timeout_seconds=1)
            await asyncio.sleep(0)
        finally:
            resolver._resolution_semaphore.release()

        snapshot = prefetch.snapshot_v53()
        self.assertEqual(resolver.calls, 0)
        self.assertEqual(snapshot.admitted, 1)
        self.assertEqual(snapshot.completed_available, 1)
        self.assertEqual(snapshot.skipped_capacity, 0)


if __name__ == "__main__":
    unittest.main()
