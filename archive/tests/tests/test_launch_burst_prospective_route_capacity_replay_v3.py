import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.launch_burst_prospective_route_live_v3.replay_capacity import (
    _max_pending_depth,
    _simulate_schedule,
    _trace_finalized_wall_ns,
)


class LaunchBurstProspectiveRouteCapacityReplayV3Tests(unittest.TestCase):
    def test_trace_footer_finalized_clock_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chunk-000001.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"type": "trace_header"}),
                        json.dumps({"type": "fixture_event"}),
                        json.dumps({"type": "trace_footer", "finalized_wall_ns": 123456789}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(_trace_finalized_wall_ns(path), 123456789)

    def test_schedule_replays_original_arrival_clock_and_queueing(self):
        records = [
            {"chunk": "chunk-1", "finalized_wall_ns": 1_000_000_000, "service_ms": 1500.0},
            {"chunk": "chunk-2", "finalized_wall_ns": 2_000_000_000, "service_ms": 1500.0},
            {"chunk": "chunk-3", "finalized_wall_ns": 3_000_000_000, "service_ms": 100.0},
        ]
        schedule = _simulate_schedule(records)
        self.assertEqual(schedule[0]["simulated_queue_wait_ms"], 0.0)
        self.assertEqual(schedule[1]["simulated_queue_wait_ms"], 500.0)
        self.assertEqual(schedule[2]["simulated_queue_wait_ms"], 1000.0)
        self.assertGreaterEqual(_max_pending_depth(schedule), 1)

    def test_fast_service_keeps_queue_wait_zero(self):
        records = [
            {"chunk": "chunk-1", "finalized_wall_ns": 1_000_000_000, "service_ms": 100.0},
            {"chunk": "chunk-2", "finalized_wall_ns": 2_000_000_000, "service_ms": 100.0},
            {"chunk": "chunk-3", "finalized_wall_ns": 3_000_000_000, "service_ms": 100.0},
        ]
        schedule = _simulate_schedule(records)
        self.assertEqual([row["simulated_queue_wait_ms"] for row in schedule], [0.0, 0.0, 0.0])
        self.assertEqual(_max_pending_depth(schedule), 0)


if __name__ == "__main__":
    unittest.main()
