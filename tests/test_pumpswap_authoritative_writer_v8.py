from __future__ import annotations

from contextlib import nullcontext
import unittest
from unittest.mock import patch

import src.pumpswap_authoritative_writer_v8 as admission
import src.pumpswap_normalized_persistence_v4 as writer_module
import unified_market_route_research_smoke_tailfix_v8 as v8


class PumpSwapAuthoritativeWriterV8Tests(unittest.IsolatedAsyncioTestCase):
    async def test_v8_installs_and_restores_causal_authoritative_stage(self):
        original = writer_module._persist_prepared_batch_db_stage
        seen = []

        async def fake_v7(**kwargs):
            self.assertIsNot(writer_module._persist_prepared_batch_db_stage, original)
            seen.append(True)

        with patch.object(v8.tailfix_v7, "run_smoke_tailfix_v7", side_effect=fake_v7):
            await v8.run_smoke_tailfix_v8()

        self.assertEqual(seen, [True])
        self.assertIs(writer_module._persist_prepared_batch_db_stage, original)

    def test_causal_wrapper_preserves_stage_result_and_admits_causal_priority(self):
        entered = []

        def stage(items):
            entered.append(tuple(items))
            return ("result",)

        with patch.object(admission, "sqlite_write_admission", return_value=nullcontext()) as gate:
            wrapped = admission.causal_authoritative_stage(stage)
            observed = wrapped(("a", "b"))

        self.assertEqual(observed, ("result",))
        self.assertEqual(entered, [("a", "b")])
        gate.assert_called_once_with(admission.CAUSAL_PRIORITY)


if __name__ == "__main__":
    unittest.main()
