from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import patch

from src.pumpswap_normalized_persistence import PumpSwapNormalizedPersistResult
from src.pumpswap_normalized_persistence_v3 import PreparedPumpSwapPersistenceV3
from src.pumpswap_normalized_persistence_v4 import PumpSwapSQLiteThreadedMicrobatchWriter


class V68WriterBatch64ContractTests(unittest.TestCase):
    def test_batch64_preserves_fifo_result_mapping_and_bound(self):
        prepared = tuple(
            PreparedPumpSwapPersistenceV3(
                acquisition_run_key="v68-release-test",
                transaction_key=f"sig-{index:03d}",
                lifecycle_writes=(),
                trade_writes=(),
                unresolved_trades=0,
                role_filtered_trades=0,
                role_filtered_lifecycle=0,
                resolver_and_normalize_seconds=0.0,
            )
            for index in range(96)
        )
        observed_batches: list[tuple[str, ...]] = []

        def fake_stage(items):
            started = time.perf_counter()
            keys = tuple(item.transaction_key for item in items)
            observed_batches.append(keys)
            results = tuple(
                PumpSwapNormalizedPersistResult(
                    newly_persisted_trades=1,
                    duplicate_or_replayed_trades=0,
                    unresolved_trades=0,
                    role_filtered_trades=0,
                    newly_persisted_lifecycle=0,
                    role_filtered_lifecycle=0,
                    affected_tokens=(item.transaction_key,),
                )
                for item in items
            )
            return results, started, time.perf_counter()

        with patch(
            "src.pumpswap_normalized_persistence_v4._persist_prepared_batch_db_stage",
            side_effect=fake_stage,
        ):
            writer = PumpSwapSQLiteThreadedMicrobatchWriter(
                batch_size=64,
                max_wait_ms=10,
            )
            futures = [writer.enqueue(item) for item in prepared]
            deadline = time.time() + 2.0
            while not all(future.done() for future in futures) and time.time() < deadline:
                time.sleep(0.005)
            self.assertTrue(all(future.done() for future in futures))
            results = [future.result() for future in futures]
            asyncio.run(writer.close(cancel_pending=False))

        submitted_keys = [item.transaction_key for item in prepared]
        returned_keys = [result.affected_tokens[0] for result in results]
        flattened_batches = [key for batch in observed_batches for key in batch]

        self.assertEqual(writer.batch_size, 64)
        self.assertEqual(returned_keys, submitted_keys)
        self.assertEqual(flattened_batches, submitted_keys)
        self.assertEqual(sum(writer.batch_sizes), 96)
        self.assertTrue(writer.batch_sizes)
        self.assertGreaterEqual(min(writer.batch_sizes), 1)
        self.assertLessEqual(max(writer.batch_sizes), 64)


if __name__ == "__main__":
    unittest.main()
