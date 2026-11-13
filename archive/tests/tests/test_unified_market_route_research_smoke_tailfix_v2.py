from __future__ import annotations

import contextlib
import io
from types import SimpleNamespace
import unittest

import unified_market_route_research_smoke_tailfix_v2 as tailfix


class TailfixV2WrapperTests(unittest.IsolatedAsyncioTestCase):
    def test_composed_resolver_keeps_v53_trace_and_tailfix_transport(self):
        self.assertTrue(
            issubclass(
                tailfix.TracedSharedTransportResolverTailfixV2,
                tailfix.TracedDeadlineBoundedResolverV53,
            )
        )
        self.assertTrue(
            issubclass(
                tailfix.TracedSharedTransportResolverTailfixV2,
                tailfix.SharedTransportDeadlineResolverTailfixV2,
            )
        )
        self.assertIs(
            tailfix.TracedSharedTransportResolverTailfixV2._fetch_batch,
            tailfix.SharedTransportDeadlineResolverTailfixV2._fetch_batch,
        )

    async def test_installs_composed_resolver_at_v53_seam_and_restores_global(self):
        original_global = tailfix.v53.TracedDeadlineBoundedResolverV53
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
            observed["during"] = tailfix.v53.TracedDeadlineBoundedResolverV53
            # Emulate construction side effects from the composed MRO. The SharedTransport base
            # owns the v2 diagnostic handle used after the inherited smoke returns.
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
            tailfix.TracedSharedTransportResolverTailfixV2,
        )
        self.assertIs(tailfix.v53.TracedDeadlineBoundedResolverV53, original_global)
        text = output.getvalue()
        self.assertIn("TAILFIX V2 SHARED RPC TRANSPORT", text)
        self.assertIn("transport_limit_violations=0", text)

    async def test_fails_closed_when_v53_path_does_not_construct_tailfix_resolver(self):
        original_global = tailfix.v53.TracedDeadlineBoundedResolverV53
        original_base = tailfix._BASE_TAILFIX_V1_RUN_SMOKE

        async def fake_base(**_kwargs):
            # This specifically protects against the live failure where the wrong module symbol
            # was patched and v53 silently installed its own resolver instead.
            self.assertIs(
                tailfix.v53.TracedDeadlineBoundedResolverV53,
                tailfix.TracedSharedTransportResolverTailfixV2,
            )

        tailfix._BASE_TAILFIX_V1_RUN_SMOKE = fake_base
        tailfix.SharedTransportDeadlineResolverTailfixV2.last_instance = None
        try:
            with self.assertRaisesRegex(RuntimeError, "traced resolver was not installed"):
                await tailfix.run_smoke_tailfix_v2()
        finally:
            tailfix._BASE_TAILFIX_V1_RUN_SMOKE = original_base
            tailfix.v53.TracedDeadlineBoundedResolverV53 = original_global
            tailfix.SharedTransportDeadlineResolverTailfixV2.last_instance = None

    async def test_fails_closed_on_transport_limit_violation(self):
        original_global = tailfix.v53.TracedDeadlineBoundedResolverV53
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
            self.assertIs(
                tailfix.v53.TracedDeadlineBoundedResolverV53,
                tailfix.TracedSharedTransportResolverTailfixV2,
            )
            tailfix.SharedTransportDeadlineResolverTailfixV2.last_instance = FakeInstance()

        tailfix._BASE_TAILFIX_V1_RUN_SMOKE = fake_base
        try:
            with self.assertRaisesRegex(RuntimeError, "RPC transport ceiling"):
                await tailfix.run_smoke_tailfix_v2()
        finally:
            tailfix._BASE_TAILFIX_V1_RUN_SMOKE = original_base
            tailfix.SharedTransportDeadlineResolverTailfixV2.last_instance = None
            tailfix.v53.TracedDeadlineBoundedResolverV53 = original_global


if __name__ == "__main__":
    unittest.main()
