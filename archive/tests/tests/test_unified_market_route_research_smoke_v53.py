from __future__ import annotations

import contextlib
import io
from types import SimpleNamespace
import unittest

from src.pumpswap_opportunistic_prefetch_v53 import OpportunisticPumpSwapIngressPrefetchV53
from src.pumpswap_resolver_wait_trace_v53 import TracedDeadlineBoundedResolverV53
import unified_market_route_research_smoke_v53 as v53


class UnifiedMarketRouteResearchSmokeV53Tests(unittest.IsolatedAsyncioTestCase):
    async def test_wrapper_installs_v53_components_restores_globals_and_prints_waits(self):
        original_base = v53._BASE_V52_RUN_SMOKE
        original_resolver = v53.v52.DeadlineBoundedParallelHedgedResolverV52
        original_prefetcher = v53.v49.PumpSwapIngressPrefetchV49
        observed = {}

        async def fake_base(**_kwargs):
            observed["resolver"] = v53.v52.DeadlineBoundedParallelHedgedResolverV52
            observed["prefetcher"] = v53.v49.PumpSwapIngressPrefetchV49
            TracedDeadlineBoundedResolverV53.last_instance = SimpleNamespace(
                resolver_wait_snapshot_v53=lambda: SimpleNamespace(
                    demand_resolve_seconds=(0.1,),
                    prefetch_resolve_seconds=(0.2,),
                    demand_pool_lock_wait_seconds=(0.01,),
                    prefetch_pool_lock_wait_seconds=(0.02,),
                    demand_capacity_wait_seconds=(0.03,),
                    prefetch_capacity_wait_seconds=(0.0,),
                    pool_lock_waits=2,
                    capacity_waits=1,
                    demand_capacity_waiters_high_water=1,
                    prefetch_capacity_waiters_high_water=0,
                    hot_pool_lock_wait_seconds=(("POOL-123456789", 0.04, 2),),
                )
            )
            OpportunisticPumpSwapIngressPrefetchV53.last_instance = SimpleNamespace(
                snapshot_v53=lambda: SimpleNamespace(
                    notifications_seen=10,
                    candidate_pools=12,
                    scheduled=8,
                    coalesced_inflight=2,
                    admitted=5,
                    skipped_capacity=2,
                    skipped_pool_busy=1,
                    completed_available=4,
                    completed_unresolved=1,
                    failed=0,
                    active=0,
                )
            )

        v53._BASE_V52_RUN_SMOKE = fake_base
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                await v53.run_smoke_v53()
        finally:
            v53._BASE_V52_RUN_SMOKE = original_base

        self.assertIs(observed["resolver"], TracedDeadlineBoundedResolverV53)
        self.assertIs(observed["prefetcher"], OpportunisticPumpSwapIngressPrefetchV53)
        self.assertIs(v53.v52.DeadlineBoundedParallelHedgedResolverV52, original_resolver)
        self.assertIs(v53.v49.PumpSwapIngressPrefetchV49, original_prefetcher)
        text = output.getvalue()
        self.assertIn("V53 OPPORTUNISTIC PREFETCH / RESOLVER WAIT DIAGNOSTIC", text)
        self.assertIn("demand_pool_lock_wait_ms", text)
        self.assertIn("demand_resolution_capacity_wait_ms", text)
        self.assertIn("skipped_capacity=2", text)
        self.assertIn("skipped_pool_busy=1", text)
        self.assertNotIn("v53_resolver_instance=missing", text)
        self.assertNotIn("v53_prefetcher_instance=missing", text)

    def test_v53_keeps_immutable_reference_to_v52_runner(self):
        self.assertIsNot(v53._BASE_V52_RUN_SMOKE, v53.run_smoke_v53)


if __name__ == "__main__":
    unittest.main()
