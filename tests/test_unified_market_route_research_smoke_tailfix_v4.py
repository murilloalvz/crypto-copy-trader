from __future__ import annotations

import unittest
from unittest.mock import patch

from src import pumpswap_pool_store
import src.sqlite_write_admission as sqlite_admission_module
from src.pumpswap_pool_mapping_fastpath_v4 import record_pumpswap_pool_mapping_fast_v4
from src.pumpswap_writer_pressure_v4 import InstrumentedPumpSwapSQLiteWriterV4
import unified_market_latency_smoke_v19 as v19
import unified_market_route_research_smoke_tailfix_v3 as tailfix_v3
import unified_market_route_research_smoke_tailfix_v4 as v4


class UnifiedMarketRouteResearchSmokeTailfixV4Tests(unittest.IsolatedAsyncioTestCase):
    async def test_v4_installs_and_restores_only_systems_seams(self):
        original_pool_record = pumpswap_pool_store.record_pumpswap_pool_mapping
        original_writer = v19.PumpSwapSQLiteThreadedMicrobatchWriter
        gate = sqlite_admission_module._GLOBAL_WRITE_ADMISSION
        original_limit = gate.resolution_max_consecutive_when_causal_waiting

        async def fake_v3(**kwargs):
            self.assertIs(
                pumpswap_pool_store.record_pumpswap_pool_mapping,
                record_pumpswap_pool_mapping_fast_v4,
            )
            self.assertIs(
                v19.PumpSwapSQLiteThreadedMicrobatchWriter,
                InstrumentedPumpSwapSQLiteWriterV4,
            )
            self.assertEqual(
                gate.resolution_max_consecutive_when_causal_waiting,
                v4.V4_RESOLUTION_MAX_CONSECUTIVE_WITH_CAUSAL_WAITING,
            )
            writer = v19.PumpSwapSQLiteThreadedMicrobatchWriter(
                batch_size=4,
                max_wait_ms=0,
            )
            await writer.close(cancel_pending=True)

        with patch.object(tailfix_v3, "run_smoke_tailfix_v3", side_effect=fake_v3):
            await v4.run_smoke_tailfix_v4(pumpswap_workers=16)

        self.assertIs(pumpswap_pool_store.record_pumpswap_pool_mapping, original_pool_record)
        self.assertIs(v19.PumpSwapSQLiteThreadedMicrobatchWriter, original_writer)
        self.assertEqual(gate.resolution_max_consecutive_when_causal_waiting, original_limit)
        self.assertIsNotNone(v4.last_writer_pressure_v4)
        self.assertIsNotNone(v4.last_fastpath_snapshot_v4)
        self.assertIsNotNone(v4.last_fairness_snapshot_v4)


if __name__ == "__main__":
    unittest.main()
