import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.pumpswap_concurrent_resolver import ConcurrentReusablePumpSwapPoolResolver


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


if __name__ == "__main__":
    unittest.main()
