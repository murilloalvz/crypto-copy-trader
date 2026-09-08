from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
import threading
import time
import unittest
from unittest.mock import patch

from src.pumpswap_pool_store import PumpSwapPoolMapping
from src.pumpswap_resolver_latency_hardening_v3 import AsyncDurablePoolResolutionMixinV3


@dataclass(frozen=True)
class _Account:
    base_mint: str
    quote_mint: str


class _FakeParent:
    def __init__(self, *args, **kwargs) -> None:
        self.acquisition_run_key = "run-v3"
        self._cache = {}
        self._pool_locks = {}
        self._resolution_semaphore = asyncio.Semaphore(2)
        self.singleflight_waits = 0
        self.store_hits = 0
        self.historical_store_hits = 0
        self.cache_hits = 0
        self.hydration_attempts = 0
        self.hydration_successes = 0
        self.hydration_failures = 0
        self.network_calls = 0
        self._v53_metrics_lock = threading.Lock()
        self._v53_timings = defaultdict(list)

    def _causal_cache_hit(self, pool: str, *, as_of: int):
        value = self._cache.get(pool)
        if value is not None and value.observed_at <= as_of:
            self.cache_hits += 1
            return value
        return None

    def _load_pool_account(self, pool: str):
        self.network_calls += 1
        time.sleep(0.03)
        return _Account(base_mint=f"base-{pool}", quote_mint="quote")


class _FakeHardenedResolver(AsyncDurablePoolResolutionMixinV3, _FakeParent):
    pass


class ResolverLatencyHardeningV3Tests(unittest.IsolatedAsyncioTestCase):
    async def test_store_reads_are_off_event_loop(self):
        resolver = _FakeHardenedResolver()
        loop_thread = threading.get_ident()
        observed_threads = []
        mapping = PumpSwapPoolMapping(
            acquisition_run_key="run-v3",
            pool_address="pool-a",
            base_mint="base-a",
            quote_mint="quote",
            observed_at=10,
            source_provider="test",
        )

        def load_current(**kwargs):
            observed_threads.append(threading.get_ident())
            return mapping

        with patch(
            "src.pumpswap_resolver_latency_hardening_v3.pumpswap_pool_store.load_pumpswap_pool_mapping",
            side_effect=load_current,
        ), patch(
            "src.pumpswap_resolver_latency_hardening_v3.pumpswap_pool_store.load_known_pumpswap_pool_mapping",
            return_value=None,
        ):
            result = await resolver.resolve("pool-a", as_of=20)

        self.assertEqual(result, mapping)
        self.assertTrue(observed_threads)
        self.assertTrue(all(thread_id != loop_thread for thread_id in observed_threads))
        snapshot = resolver.resolver_stage_snapshot_v3()
        self.assertEqual(snapshot.current_store_hits, 1)
        self.assertEqual(snapshot.event_loop_store_calls, 0)

    async def test_network_identity_is_durable_before_return(self):
        resolver = _FakeHardenedResolver()
        loop_thread = threading.get_ident()
        durable = {}
        record_threads = []
        reload_threads = []

        def load_current(*, acquisition_run_key, pool_address, as_of=None):
            reload_threads.append(threading.get_ident())
            value = durable.get(pool_address)
            if value is None:
                return None
            if as_of is not None and value.observed_at > as_of:
                return None
            return value

        def record_mapping(**kwargs):
            record_threads.append(threading.get_ident())
            durable[kwargs["pool_address"]] = PumpSwapPoolMapping(
                acquisition_run_key=kwargs["acquisition_run_key"],
                pool_address=kwargs["pool_address"],
                base_mint=kwargs["base_mint"],
                quote_mint=kwargs["quote_mint"],
                observed_at=kwargs["observed_at"],
                source_provider=kwargs["source_provider"],
            )
            return True

        with patch(
            "src.pumpswap_resolver_latency_hardening_v3.pumpswap_pool_store.load_pumpswap_pool_mapping",
            side_effect=load_current,
        ), patch(
            "src.pumpswap_resolver_latency_hardening_v3.pumpswap_pool_store.load_known_pumpswap_pool_mapping",
            return_value=None,
        ), patch(
            "src.pumpswap_resolver_latency_hardening_v3.pumpswap_pool_store.record_pumpswap_pool_mapping",
            side_effect=record_mapping,
        ):
            result = await resolver.resolve("pool-b", as_of=int(time.time()) + 10)

        self.assertIsNotNone(result)
        self.assertEqual(result.pool_address, "pool-b")
        self.assertIn("pool-b", durable)
        self.assertEqual(resolver.network_calls, 1)
        self.assertEqual(resolver.hydration_successes, 1)
        self.assertTrue(record_threads)
        self.assertTrue(all(thread_id != loop_thread for thread_id in record_threads))
        self.assertTrue(all(thread_id != loop_thread for thread_id in reload_threads))
        snapshot = resolver.resolver_stage_snapshot_v3()
        self.assertEqual(snapshot.durable_mapping_writes, 1)
        self.assertEqual(snapshot.network_resolutions, 1)

    async def test_same_pool_remains_single_flight(self):
        resolver = _FakeHardenedResolver()
        durable = {}

        def load_current(*, acquisition_run_key, pool_address, as_of=None):
            return durable.get(pool_address)

        def record_mapping(**kwargs):
            durable[kwargs["pool_address"]] = PumpSwapPoolMapping(
                acquisition_run_key=kwargs["acquisition_run_key"],
                pool_address=kwargs["pool_address"],
                base_mint=kwargs["base_mint"],
                quote_mint=kwargs["quote_mint"],
                observed_at=kwargs["observed_at"],
                source_provider=kwargs["source_provider"],
            )
            return True

        with patch(
            "src.pumpswap_resolver_latency_hardening_v3.pumpswap_pool_store.load_pumpswap_pool_mapping",
            side_effect=load_current,
        ), patch(
            "src.pumpswap_resolver_latency_hardening_v3.pumpswap_pool_store.load_known_pumpswap_pool_mapping",
            return_value=None,
        ), patch(
            "src.pumpswap_resolver_latency_hardening_v3.pumpswap_pool_store.record_pumpswap_pool_mapping",
            side_effect=record_mapping,
        ):
            first, second = await asyncio.gather(
                resolver.resolve("pool-c", as_of=int(time.time()) + 10),
                resolver.resolve("pool-c", as_of=int(time.time()) + 10),
            )

        self.assertEqual(first.base_mint, second.base_mint)
        self.assertEqual(resolver.network_calls, 1)
        self.assertGreaterEqual(resolver.singleflight_waits, 1)
        self.assertGreaterEqual(resolver.cache_hits, 1)


if __name__ == "__main__":
    unittest.main()
