from __future__ import annotations

import contextlib
import io
import threading
import unittest

import unified_market_route_research_smoke_tailfix_v1 as tailfix


class _Token:
    def __init__(self, mint: str):
        self.token_mint = mint
        self.trigger = object()


class PreparedPumpRadarV5:
    def __init__(self, mint: str):
        self.tokens = (_Token(mint),)


class PreparedPumpSwapRadarV5:
    def __init__(self, mint: str):
        self.tokens = (_Token(mint),)


class UnifiedMarketRouteResearchSmokeTailfixV1Tests(unittest.IsolatedAsyncioTestCase):
    async def test_wrapper_routes_both_sources_and_restores_runner(self):
        original_runner = tailfix.v19._run_sync_stage
        original_base = tailfix._BASE_V54_RUN_SMOKE
        barrier = threading.Barrier(2)

        def stateful_finalize(_prepared):
            barrier.wait(timeout=1.0)
            return object()

        async def fake_base(**_kwargs):
            import asyncio

            await asyncio.gather(
                tailfix.v19._run_sync_stage(
                    stateful_finalize,
                    PreparedPumpRadarV5("PUMP-TOKEN"),
                    executor=object(),
                ),
                tailfix.v19._run_sync_stage(
                    stateful_finalize,
                    PreparedPumpSwapRadarV5("PS-TOKEN"),
                    executor=object(),
                ),
            )

        tailfix._BASE_V54_RUN_SMOKE = fake_base
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                await tailfix.run_smoke_tailfix_v1()
        finally:
            tailfix._BASE_V54_RUN_SMOKE = original_base

        self.assertIs(tailfix.v19._run_sync_stage, original_runner)
        text = output.getvalue()
        self.assertIn("TAILFIX V1 CROSS-SOURCE TOKEN COMMIT LANES", text)
        self.assertIn("pump_calls=1", text)
        self.assertIn("pumpswap_calls=1", text)
        self.assertIn("fallback_calls=0", text)
        self.assertIn("max_parallel_calls=2", text)
        self.assertIn("same_token_overlap_violations=0", text)

    async def test_wrapper_fails_closed_if_unclassified_stage_reaches_executor(self):
        original_base = tailfix._BASE_V54_RUN_SMOKE

        class UnknownPrepared:
            tokens = (_Token("UNKNOWN"),)

        async def fake_inherited(function, /, *args, executor=None, **kwargs):
            return function(*args, **kwargs)

        original_runner = tailfix.v19._run_sync_stage
        tailfix.v19._run_sync_stage = fake_inherited

        async def fake_base(**_kwargs):
            await tailfix.v19._run_sync_stage(
                lambda _prepared: None,
                UnknownPrepared(),
                executor=object(),
            )
            # Exercise both recognized lanes so the fail-closed reason is specifically fallback.
            await tailfix.v19._run_sync_stage(
                lambda _prepared: None,
                PreparedPumpRadarV5("A"),
                executor=object(),
            )
            await tailfix.v19._run_sync_stage(
                lambda _prepared: None,
                PreparedPumpSwapRadarV5("B"),
                executor=object(),
            )

        tailfix._BASE_V54_RUN_SMOKE = fake_base
        try:
            with self.assertRaisesRegex(RuntimeError, "unclassified synchronous stateful stage"):
                await tailfix.run_smoke_tailfix_v1()
        finally:
            tailfix._BASE_V54_RUN_SMOKE = original_base
            tailfix.v19._run_sync_stage = original_runner


if __name__ == "__main__":
    unittest.main()
