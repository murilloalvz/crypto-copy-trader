from __future__ import annotations

import contextlib
import io
import unittest

from src.pumpswap_demand_only_prefetch_v54 import DemandOnlyPumpSwapIngressPrefetchV54
import unified_market_route_research_smoke_v54 as v54


class UnifiedMarketRouteResearchSmokeV54Tests(unittest.IsolatedAsyncioTestCase):
    async def test_wrapper_installs_demand_only_prefetch_restores_global_and_prints_diagnostic(self):
        original_base = v54._BASE_V53_RUN_SMOKE
        original_prefetch = v54.v53.OpportunisticPumpSwapIngressPrefetchV53
        observed = {}

        async def fake_base(**_kwargs):
            observed["prefetch"] = v54.v53.OpportunisticPumpSwapIngressPrefetchV53
            v54.v53.OpportunisticPumpSwapIngressPrefetchV53()

        v54._BASE_V53_RUN_SMOKE = fake_base
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                await v54.run_smoke_v54()
        finally:
            v54._BASE_V53_RUN_SMOKE = original_base

        self.assertIs(observed["prefetch"], DemandOnlyPumpSwapIngressPrefetchV54)
        self.assertIs(v54.v53.OpportunisticPumpSwapIngressPrefetchV53, original_prefetch)
        text = output.getvalue()
        self.assertIn("V54 DEMAND-ONLY RESOLVER ADMISSION DIAGNOSTIC", text)
        self.assertIn("scheduled=0", text)
        self.assertIn("skipped_speculative=0", text)
        self.assertNotIn("v54_prefetcher_instance=missing", text)

    def test_v54_keeps_immutable_reference_to_v53_runner(self):
        self.assertIsNot(v54._BASE_V53_RUN_SMOKE, v54.run_smoke_v54)


if __name__ == "__main__":
    unittest.main()
