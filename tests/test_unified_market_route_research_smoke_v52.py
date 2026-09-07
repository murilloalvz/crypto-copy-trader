from __future__ import annotations

import contextlib
import io
from types import SimpleNamespace
import unittest

from src.pumpswap_deadline_hedged_resolver_v52 import (
    DeadlineBoundedParallelHedgedResolverV52,
    HedgeWallDeadlineSnapshotV52,
)
import unified_market_route_research_smoke_v52 as v52


class UnifiedMarketRouteResearchSmokeV52Tests(unittest.IsolatedAsyncioTestCase):
    async def test_wrapper_installs_deadline_resolver_and_restores_global(self):
        original_global = v52.v41.ParallelHedgedBatchedBoundedResolverV41
        original_base = v52._BASE_V51_RUN_SMOKE
        observed = {}

        async def fake_base(**_kwargs):
            observed["during"] = v52.v41.ParallelHedgedBatchedBoundedResolverV41
            fake = SimpleNamespace(
                hedged_batch_calls=3,
                hedged_endpoint_requests=6,
                hedged_all_failed=1,
                network_batch_calls=2,
                hedge_deadline_snapshot_v52=lambda: HedgeWallDeadlineSnapshotV52(
                    wall_deadline_seconds=3.0,
                    deadline_expirations=1,
                    fetch_seconds=(0.1, 2.9, 3.0),
                ),
            )
            DeadlineBoundedParallelHedgedResolverV52.last_instance = fake

        v52._BASE_V51_RUN_SMOKE = fake_base
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                await v52.run_smoke_v52()
        finally:
            v52._BASE_V51_RUN_SMOKE = original_base

        self.assertIs(
            observed["during"],
            DeadlineBoundedParallelHedgedResolverV52,
        )
        self.assertIs(v52.v41.ParallelHedgedBatchedBoundedResolverV41, original_global)
        text = output.getvalue()
        self.assertIn("V52 PUMPSWAP HEDGED RPC WALL-DEADLINE DIAGNOSTIC", text)
        self.assertIn("hedge_wall_deadline_seconds=3.000", text)
        self.assertIn("hedge_wall_deadline_expirations=1", text)
        self.assertNotIn("v52_resolver_instance=missing", text)

    def test_v52_keeps_immutable_reference_to_v51_runner(self):
        self.assertIsNot(v52._BASE_V51_RUN_SMOKE, v52.run_smoke_v52)


if __name__ == "__main__":
    unittest.main()
