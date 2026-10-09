from __future__ import annotations

import unittest
from unittest.mock import patch

import unified_market_execution_quote_smoke_v34 as v34
import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v27 as v27


class UnifiedMarketExecutionQuoteSmokeV34Tests(unittest.IsolatedAsyncioTestCase):
    async def test_wrapper_restores_scheduler_and_episode_cache_classes(self):
        original_scheduler = v19.ReadyAssetScheduler
        original_cache = v27._EpisodeContinuationCache
        seen = {}

        async def fake_v33_run(**kwargs):
            seen["scheduler_class"] = v19.ReadyAssetScheduler
            seen["cache_class"] = v27._EpisodeContinuationCache
            cache = v27._EpisodeContinuationCache()
            scheduler = v19.ReadyAssetScheduler()
            seen["cache"] = cache
            seen["scheduler"] = scheduler

        with patch.object(v34.v33, "run_smoke_v33", new=fake_v33_run):
            await v34.run_smoke_v34(
                hydration_batch_size=64,
                hydration_batch_max_wait_ms=5,
                hedge_endpoints=2,
            )

        self.assertIsNot(seen["scheduler_class"], original_scheduler)
        self.assertIsNot(seen["cache_class"], original_cache)
        self.assertIs(v19.ReadyAssetScheduler, original_scheduler)
        self.assertIs(v27._EpisodeContinuationCache, original_cache)

    async def test_unknown_payload_fails_closed_to_stateful(self):
        original_scheduler = v19.ReadyAssetScheduler
        original_cache = v27._EpisodeContinuationCache
        outcome = {}

        async def fake_v33_run(**kwargs):
            v27._EpisodeContinuationCache()
            scheduler = v19.ReadyAssetScheduler()
            reservation = scheduler.reserve(("asset",))
            scheduler.submit(object(), reservation)
            outcome["ready"] = scheduler._ready.get_nowait()
            scheduler.ready_task_done()
            await scheduler.complete(outcome["ready"].reservation)
            outcome["demotions"] = scheduler.demoted_pending_jobs

        with patch.object(v34.v33, "run_smoke_v33", new=fake_v33_run):
            await v34.run_smoke_v34(
                hydration_batch_size=64,
                hydration_batch_max_wait_ms=5,
                hedge_endpoints=2,
            )

        self.assertEqual(outcome["demotions"], 0)
        self.assertIs(v19.ReadyAssetScheduler, original_scheduler)
        self.assertIs(v27._EpisodeContinuationCache, original_cache)


if __name__ == "__main__":
    unittest.main()
