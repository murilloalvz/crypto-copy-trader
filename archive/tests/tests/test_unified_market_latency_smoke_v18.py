import asyncio
import unittest
from unittest.mock import patch

import unified_market_latency_smoke_v12 as v12
import unified_market_latency_smoke_v17 as v17
import unified_market_latency_smoke_v18 as v18


class UnifiedMarketLatencySmokeV18Tests(unittest.TestCase):
    def test_decouples_prepare_submitters_from_executor_threads_and_restores_factory(self):
        original_factory = v12.ThreadPoolExecutor
        observed = {}

        async def fake_run_smoke_v17(**kwargs):
            observed["kwargs"] = kwargs
            executor = v12.ThreadPoolExecutor(
                max_workers=999,
                thread_name_prefix="pumpswap-prepare",
            )
            try:
                observed["executor_workers"] = executor._max_workers
            finally:
                executor.shutdown(wait=True, cancel_futures=True)
            return v17.ThreadedWriterDiagnostics()

        with patch.object(v17, "run_smoke_v17", side_effect=fake_run_smoke_v17):
            diagnostics = asyncio.run(
                v18.run_smoke_v18(
                    run_key="test-v18",
                    duration_seconds=1,
                    commitment="confirmed",
                    max_hydrations=1,
                    rpc_timeout_seconds=1,
                    pump_batch_size=2,
                    pump_batch_max_wait_ms=1,
                    pumpswap_workers=64,
                    pumpswap_prepare_submitters=48,
                    pumpswap_prepare_executor_workers=12,
                    pumpswap_writer_batch_size=2,
                    pumpswap_writer_batch_max_wait_ms=1,
                    max_concurrent_resolutions=1,
                    queue_size=10,
                )
            )

        self.assertIsInstance(diagnostics, v17.ThreadedWriterDiagnostics)
        self.assertEqual(observed["kwargs"]["pumpswap_radar_workers"], 48)
        self.assertEqual(observed["executor_workers"], 12)
        self.assertIs(v12.ThreadPoolExecutor, original_factory)

    def test_rejects_non_positive_prepare_counts(self):
        with self.assertRaises(ValueError):
            asyncio.run(
                v18.run_smoke_v18(
                    run_key="test-v18",
                    duration_seconds=1,
                    commitment="confirmed",
                    max_hydrations=1,
                    rpc_timeout_seconds=1,
                    pump_batch_size=2,
                    pump_batch_max_wait_ms=1,
                    pumpswap_workers=1,
                    pumpswap_prepare_submitters=0,
                    pumpswap_prepare_executor_workers=12,
                    pumpswap_writer_batch_size=2,
                    pumpswap_writer_batch_max_wait_ms=1,
                    max_concurrent_resolutions=1,
                    queue_size=10,
                )
            )


if __name__ == "__main__":
    unittest.main()
