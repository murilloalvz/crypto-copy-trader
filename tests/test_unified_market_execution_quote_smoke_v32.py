import unittest
from unittest.mock import patch

import unified_market_execution_quote_smoke_v32 as v32
import unified_market_latency_smoke_v19 as v19


class UnifiedMarketExecutionQuoteSmokeV32Tests(unittest.IsolatedAsyncioTestCase):
    async def test_v32_patches_only_resolver_for_nested_v31_run_and_restores_it(self):
        original = v19.BoundedConcurrentResolver
        seen = []

        async def fake_v31_run(**kwargs):
            seen.append(v19.BoundedConcurrentResolver)
            self.assertTrue(issubclass(v19.BoundedConcurrentResolver, v32.BatchedBoundedConcurrentResolverV32))

        with patch.object(v32.v31, "run_smoke_v31", side_effect=fake_v31_run):
            await v32.run_smoke_v32(
                hydration_batch_size=64,
                hydration_batch_max_wait_ms=5,
            )

        self.assertEqual(len(seen), 1)
        self.assertIs(v19.BoundedConcurrentResolver, original)

    async def test_v32_restores_original_resolver_even_if_nested_run_raises(self):
        original = v19.BoundedConcurrentResolver

        async def fail(**kwargs):
            raise RuntimeError("boom")

        with patch.object(v32.v31, "run_smoke_v31", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                await v32.run_smoke_v32(
                    hydration_batch_size=64,
                    hydration_batch_max_wait_ms=5,
                )

        self.assertIs(v19.BoundedConcurrentResolver, original)


if __name__ == "__main__":
    unittest.main()
