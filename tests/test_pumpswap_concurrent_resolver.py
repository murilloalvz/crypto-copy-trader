import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.pumpswap_concurrent_resolver import ConcurrentReusablePumpSwapPoolResolver
from src.pumpswap_pool_store import PumpSwapPoolMapping, record_pumpswap_pool_mapping


class ConcurrentReusableResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_pool_is_single_flight(self):
        resolver = ConcurrentReusablePumpSwapPoolResolver(
            acquisition_run_key="run",
            client=SimpleNamespace(),
            max_concurrent_resolutions=2,
        )
        active = 0
        max_active = 0

        async def fake_parent_resolve(_self, pool_address: str, *, as_of: int):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.02)
            active -= 1
            return None

        with patch(
            "src.pumpswap_concurrent_resolver.ReusablePumpSwapPoolResolver.resolve",
            new=fake_parent_resolve,
        ):
            await asyncio.gather(
                resolver.resolve("POOL", as_of=1000),
                resolver.resolve("POOL", as_of=1000),
            )

        self.assertEqual(max_active, 1)
        self.assertGreaterEqual(resolver.singleflight_waits, 1)

    async def test_different_pools_can_resolve_concurrently_with_bound(self):
        resolver = ConcurrentReusablePumpSwapPoolResolver(
            acquisition_run_key="run",
            client=SimpleNamespace(),
            max_concurrent_resolutions=2,
        )
        active = 0
        max_active = 0

        async def fake_parent_resolve(_self, pool_address: str, *, as_of: int):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.02)
            active -= 1
            return None

        with patch(
            "src.pumpswap_concurrent_resolver.ReusablePumpSwapPoolResolver.resolve",
            new=fake_parent_resolve,
        ):
            await asyncio.gather(
                resolver.resolve("POOL-A", as_of=1000),
                resolver.resolve("POOL-B", as_of=1000),
                resolver.resolve("POOL-C", as_of=1000),
            )

        self.assertEqual(max_active, 2)

    async def test_causal_cache_hit_bypasses_exhausted_resolution_semaphore(self):
        resolver = ConcurrentReusablePumpSwapPoolResolver(
            acquisition_run_key="run",
            client=SimpleNamespace(),
            max_concurrent_resolutions=1,
        )
        resolver._cache["POOL"] = PumpSwapPoolMapping(
            acquisition_run_key="run",
            pool_address="POOL",
            base_mint="BASE",
            quote_mint="QUOTE",
            observed_at=100,
            source_provider="cached",
        )

        await resolver._resolution_semaphore.acquire()
        try:
            mapping = await asyncio.wait_for(
                resolver.resolve("POOL", as_of=120),
                timeout=0.05,
            )
        finally:
            resolver._resolution_semaphore.release()

        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(mapping.base_mint, "BASE")
        self.assertEqual(resolver.cache_hits, 1)
        self.assertNotIn("POOL", resolver._pool_locks)

    async def test_resolution_returns_store_canonical_mapping_not_stale_parent_object(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resolver.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_pumpswap_pool_mapping(
                    acquisition_run_key="run",
                    pool_address="POOL",
                    base_mint="CANONICAL",
                    quote_mint="QUOTE",
                    observed_at=100,
                    source_provider="create",
                )
                resolver = ConcurrentReusablePumpSwapPoolResolver(
                    acquisition_run_key="run",
                    client=SimpleNamespace(),
                    max_concurrent_resolutions=2,
                )

                async def fake_parent_resolve(_self, pool_address: str, *, as_of: int):
                    return PumpSwapPoolMapping(
                        acquisition_run_key="run",
                        pool_address=pool_address,
                        base_mint="STALE",
                        quote_mint="QUOTE",
                        observed_at=110,
                        source_provider="rpc",
                    )

                with patch(
                    "src.pumpswap_concurrent_resolver.ReusablePumpSwapPoolResolver.resolve",
                    new=fake_parent_resolve,
                ):
                    mapping = await resolver.resolve("POOL", as_of=120)

        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(mapping.base_mint, "CANONICAL")
        self.assertEqual(mapping.observed_at, 100)
        self.assertEqual(resolver._cache["POOL"].base_mint, "CANONICAL")


if __name__ == "__main__":
    unittest.main()
