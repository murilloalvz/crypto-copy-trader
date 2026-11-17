import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import unified_market_latency_smoke_v14 as v14


class PrepareHiddenTimeDiagnosticsTests(unittest.TestCase):
    def test_record_separates_accounted_and_unaccounted_time(self):
        diagnostics = v14.PrepareHiddenTimeDiagnostics()
        diagnostics.record(
            internal_total=0.250,
            prepared=SimpleNamespace(
                transaction_view_read_seconds=0.050,
                history_read_seconds=0.075,
                detect_seconds=0.005,
            ),
        )

        self.assertEqual(diagnostics.internal_total_seconds, [0.250])
        self.assertEqual(diagnostics.accounted_seconds, [0.130])
        self.assertAlmostEqual(diagnostics.unaccounted_seconds[0], 0.120)

    def test_run_temporarily_patches_v11_and_v12_prepare_identity(self):
        original_v11 = v14.v11.prepare_persisted_pumpswap_notification_for_radar_v5
        original_v12 = v14.v12.prepare_persisted_pumpswap_notification_for_radar_v5
        seen = {}

        def fake_prepare(*args, **kwargs):
            return SimpleNamespace(
                transaction_view_read_seconds=0.010,
                history_read_seconds=0.020,
                detect_seconds=0.001,
            )

        async def fake_run_smoke_v13(**kwargs):
            self.assertIs(
                v14.v11.prepare_persisted_pumpswap_notification_for_radar_v5,
                v14.v12.prepare_persisted_pumpswap_notification_for_radar_v5,
            )
            prepared = await asyncio.to_thread(
                v14.v11.prepare_persisted_pumpswap_notification_for_radar_v5,
                object(),
            )
            seen["prepared"] = prepared

        with patch.object(v14, "_prepare_v5", fake_prepare), patch.object(
            v14,
            "run_smoke_v13",
            fake_run_smoke_v13,
        ):
            diagnostics = asyncio.run(
                v14.run_smoke_v14(
                    run_key="run",
                    duration_seconds=1,
                    commitment="confirmed",
                    max_hydrations=1,
                    rpc_timeout_seconds=1,
                    pump_batch_size=2,
                    pump_batch_max_wait_ms=0,
                    pumpswap_workers=1,
                    pumpswap_radar_workers=1,
                    max_concurrent_resolutions=1,
                    queue_size=1,
                )
            )

        self.assertIn("prepared", seen)
        self.assertEqual(len(diagnostics.internal_total_seconds), 1)
        self.assertIs(
            v14.v11.prepare_persisted_pumpswap_notification_for_radar_v5,
            original_v11,
        )
        self.assertIs(
            v14.v12.prepare_persisted_pumpswap_notification_for_radar_v5,
            original_v12,
        )


if __name__ == "__main__":
    unittest.main()
