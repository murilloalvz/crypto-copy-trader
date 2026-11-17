from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import unittest

from benchmarks.market_first_capacity_harness_v0.profile_one_chunk import (
    CheckpointHeartbeatV1,
    _atomic_write_json,
    _persistence_share_percent,
)
from benchmarks.market_first_capacity_harness_v0.run import StageRecorderV0


class MarketFirstCapacityProfileV1Tests(unittest.TestCase):
    def test_persistence_share_uses_trade_and_lifecycle_totals(self) -> None:
        timings = {
            "chunk_total": {"total_ms": 1000.0},
            "market_trade_persistence": {"total_ms": 600.0},
            "market_lifecycle_persistence": {"total_ms": 100.0},
        }
        self.assertAlmostEqual(_persistence_share_percent(timings), 70.0)

    def test_persistence_share_handles_missing_chunk_total(self) -> None:
        self.assertEqual(
            _persistence_share_percent(
                {"market_trade_persistence": {"total_ms": 100.0}}
            ),
            0.0,
        )

    def test_atomic_write_json_replaces_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            _atomic_write_json(path, {"status": "RUNNING"})
            _atomic_write_json(path, {"status": "COMPLETE", "value": 2})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"status": "COMPLETE", "value": 2},
            )
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_heartbeat_writes_running_checkpoint_with_stage_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "profile.json"
            recorder = StageRecorderV0()
            recorder.observe("market_trade_persistence", 100_000_000)
            heartbeat = CheckpointHeartbeatV1(
                output=output,
                recorder=recorder,
                chunk_name="chunk-000001.jsonl.gz",
                interval_seconds=0.01,
            )
            heartbeat.start()
            time.sleep(0.03)
            heartbeat.stop()
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "RUNNING")
            self.assertEqual(payload["chunk"], "chunk-000001.jsonl.gz")
            self.assertIn("market_trade_persistence", payload["stage_timings"])


if __name__ == "__main__":
    unittest.main()
