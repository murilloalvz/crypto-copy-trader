from __future__ import annotations

import contextlib
import io
import unittest

import unified_market_route_research_smoke_v51 as v51
from src.pumpswap_stateful_priority_scheduler_v51 import (
    StatefulPriorityEagerDemotingReadyAssetSchedulerV51,
)


class UnifiedMarketRouteResearchSmokeV51Tests(unittest.IsolatedAsyncioTestCase):
    async def test_wrapper_installs_priority_scheduler_and_restores_global(self):
        original_global = v51.v42.EagerDemotingReadyAssetSchedulerV42
        original_base = v51._BASE_V50_RUN_SMOKE
        observed = {}

        async def fake_base(**_kwargs):
            observed["during"] = v51.v42.EagerDemotingReadyAssetSchedulerV42
            scheduler = v51.v42.EagerDemotingReadyAssetSchedulerV42(
                should_remain_stateful=lambda _payload: True
            )
            reservation = scheduler.reserve(("asset",))
            scheduler.submit("payload", reservation)
            work = await scheduler.get_ready()
            await scheduler.complete(work.reservation)
            scheduler.ready_task_done()

        v51._BASE_V50_RUN_SMOKE = fake_base
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                await v51.run_smoke_v51()
        finally:
            v51._BASE_V50_RUN_SMOKE = original_base

        self.assertIs(
            observed["during"],
            StatefulPriorityEagerDemotingReadyAssetSchedulerV51,
        )
        self.assertIs(v51.v42.EagerDemotingReadyAssetSchedulerV42, original_global)
        text = output.getvalue()
        self.assertIn("V51 STATEFUL-PRIORITY READY-QUEUE DIAGNOSTIC", text)
        self.assertIn("stateful_enqueued=1", text)
        self.assertIn("demoted_enqueued=0", text)
        self.assertNotIn("v51_scheduler_instance=missing", text)

    def test_v51_keeps_immutable_reference_to_v50_runner(self):
        self.assertIsNot(v51._BASE_V50_RUN_SMOKE, v51.run_smoke_v51)


if __name__ == "__main__":
    unittest.main()
