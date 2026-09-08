from __future__ import annotations

import contextlib
import io
from types import SimpleNamespace
import unittest

import unified_market_route_research_smoke_tailfix_v2 as tailfix


class TailfixV2WrapperTests(unittest.IsolatedAsyncioTestCase):
    async def test_installs_shared_transport_resolver_and_restores_global(self):
        original_global = tailfix.v52.DeadlineBoundedParallelHedgedResolverV52
        original_base = tailfix._BASE_TAILFIX_V1_RUN_SMOKE
        observed = {}

        class FakeInstance:
            def tailfix_snapshot_v2(self):
                return SimpleNamespace(
                    transport_workers=18,
                    active_transports=0,
                    max_active_transports=2,
                    transport_limit_violations=0,
                    decisions_released=3,
                    residual_cleanup_pending=0,
                    residual_cleanup_high_water=1,
                    decision_release_seconds=(0.01, 0.02),
                    residual_cleanup_seconds=(0.03,),
                )

        async def fake_base(**_kwargs):
            observed["during"] = tailfix.v52.DeadlineBoundedParallelHedgedResolverV52
            tailfix.SharedTransportDeadlineResolverTailfixV2.last_instance = FakeInstance()

        tailfix._BASE_TAILFIX_V1_RUN_SMOKE = fake_base
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                await tailfix.run_smoke_tailfix_v2()
        finally:
            tailfix._BASE_TAILFIX_V1_RUN_SMOKE = original_base
            tailfix.SharedTransportDeadlineResolverTailfixV2.last_instance = None

        self.assertIs(
            observed["during"],
            tailfix.SharedTransportDeadlineResolverTailfixV2,
        )
        self.assertIs(tailfix.v52.DeadlineBoundedParallelHedgedResolverV52, original_global)
        text = output.getvalue()
        self.assertIn("TAILFIX V2 SHARED RPC TRANSPORT", text)
        self.assertIn("transport_limit_violations=0", text)

    async def test_fails_closed_on_transport_limit_violation(self):
        original_global = tailfix.v52.DeadlineBoundedParallelHedgedResolverV52
        original_base = tailfix._BASE_TAILFIX_V1_RUN_SMOKE

        class FakeInstance:
            def tailfix_snapshot_v2(self):
                return SimpleNamespace(
                    transport_workers=18,
                    active_transports=0,
                    max_active_transports=19,
                    transport_limit_violations=1,
                    decisions_released=1,
                    residual_cleanup_pending=0,
                    residual_cleanup_high_water=0,
                    decision_release_seconds=(0.01,),
                    residual_cleanup_seconds=(),
                )

        async def fake_base(**_kwargs):
            tailfix.SharedTransportDeadlineResolverTailfixV2.last_instance = FakeInstance()

        tailfix._BASE_TAILFIX_V1_RUN_SMOKE = fake_base
        try:
            with self.assertRaisesRegex(RuntimeError, "RPC transport ceiling"):
                await tailfix.run_smoke_tailfix_v2()
        finally:
            tailfix._BASE_TAILFIX_V1_RUN_SMOKE = original_base
            tailfix.SharedTransportDeadlineResolverTailfixV2.last_instance = None
            tailfix.v52.DeadlineBoundedParallelHedgedResolverV52 = original_global


if __name__ == "__main__":
    unittest.main()
