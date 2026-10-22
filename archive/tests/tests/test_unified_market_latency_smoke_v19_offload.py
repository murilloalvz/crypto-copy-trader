import asyncio
import contextvars
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from unified_market_latency_smoke_v19 import _run_sync_stage


_probe = contextvars.ContextVar("probe", default="missing")


class UnifiedMarketLatencySmokeV19OffloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_inline_stage_runs_on_event_loop_thread(self):
        caller_thread = threading.get_ident()

        def stage():
            return threading.get_ident()

        self.assertEqual(await _run_sync_stage(stage), caller_thread)

    async def test_executor_stage_runs_off_loop_and_preserves_context(self):
        caller_thread = threading.get_ident()
        token = _probe.set("context-ok")
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="radar-test")
        try:
            def stage(value):
                return threading.get_ident(), _probe.get(), value

            worker_thread, observed_context, value = await _run_sync_stage(
                stage,
                7,
                executor=executor,
            )
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
            _probe.reset(token)

        self.assertNotEqual(worker_thread, caller_thread)
        self.assertEqual(observed_context, "context-ok")
        self.assertEqual(value, 7)

    async def test_single_worker_executor_serializes_submitted_stages(self):
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="radar-test")
        order = []
        try:
            def stage(value):
                order.append(value)
                return threading.get_ident()

            first_thread = await _run_sync_stage(stage, 1, executor=executor)
            second_thread = await _run_sync_stage(stage, 2, executor=executor)
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

        self.assertEqual(order, [1, 2])
        self.assertEqual(first_thread, second_thread)


if __name__ == "__main__":
    unittest.main()
