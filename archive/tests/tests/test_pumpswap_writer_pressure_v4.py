from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import patch

from src.pumpswap_normalized_persistence import PumpSwapNormalizedPersistResult
from src.pumpswap_writer_pressure_v4 import InstrumentedPumpSwapSQLiteWriterV4


class _Prepared:
    resolver_and_normalize_seconds = 0.0


def _fake_batch_stage(items):
    started = time.perf_counter()
    time.sleep(0.01)
    results = tuple(
        PumpSwapNormalizedPersistResult(
            newly_persisted_trades=1,
            duplicate_or_replayed_trades=0,
            unresolved_trades=0,
            role_filtered_trades=0,
            newly_persisted_lifecycle=0,
            role_filtered_lifecycle=0,
            affected_tokens=("T",),
        )
        for _ in items
    )
    finished = time.perf_counter()
    return results, started, finished


class PumpSwapWriterPressureV4Tests(unittest.IsolatedAsyncioTestCase):
    async def test_writer_pressure_tracks_submissions_completions_and_batches(self):
        with patch(
            "src.pumpswap_normalized_persistence_v4._persist_prepared_batch_db_stage",
            side_effect=_fake_batch_stage,
        ):
            writer = InstrumentedPumpSwapSQLiteWriterV4(
                batch_size=8,
                max_wait_ms=2,
            )
            results = await asyncio.gather(
                *(writer.submit(_Prepared()) for _ in range(12))
            )
            await writer.close(cancel_pending=True)

        self.assertEqual(len(results), 12)
        snapshot = writer.pressure_snapshot_v4()
        self.assertEqual(snapshot.submitted, 12)
        self.assertEqual(snapshot.completed, 12)
        self.assertEqual(snapshot.pending_at_close, 0)
        self.assertGreaterEqual(snapshot.queue_high_water, 1)
        self.assertGreater(snapshot.batch_count, 0)
        self.assertLessEqual(snapshot.max_batch_size, 8)
        self.assertEqual(snapshot.configured_batch_size, 8)
        self.assertGreater(snapshot.batch_fill_pct, 0.0)

    async def test_close_records_pending_pressure_when_queue_is_cancelled(self):
        def slow_stage(items):
            started = time.perf_counter()
            time.sleep(0.08)
            results = tuple(
                PumpSwapNormalizedPersistResult(
                    newly_persisted_trades=1,
                    duplicate_or_replayed_trades=0,
                    unresolved_trades=0,
                    role_filtered_trades=0,
                    newly_persisted_lifecycle=0,
                    role_filtered_lifecycle=0,
                    affected_tokens=("T",),
                )
                for _ in items
            )
            return results, started, time.perf_counter()

        with patch(
            "src.pumpswap_normalized_persistence_v4._persist_prepared_batch_db_stage",
            side_effect=slow_stage,
        ):
            writer = InstrumentedPumpSwapSQLiteWriterV4(
                batch_size=1,
                max_wait_ms=0,
            )
            tasks = [asyncio.create_task(writer.submit(_Prepared())) for _ in range(8)]
            await asyncio.sleep(0.01)
            await writer.close(cancel_pending=True)
            await asyncio.gather(*tasks, return_exceptions=True)

        snapshot = writer.pressure_snapshot_v4()
        self.assertEqual(snapshot.submitted, 8)
        self.assertGreater(snapshot.queue_before_close, 0)
        self.assertGreater(snapshot.pending_at_close, 0)
        self.assertLessEqual(snapshot.completed, snapshot.submitted)


if __name__ == "__main__":
    unittest.main()
