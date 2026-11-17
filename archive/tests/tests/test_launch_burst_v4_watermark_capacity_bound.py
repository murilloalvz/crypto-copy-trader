import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.launch_burst_prospective_route_live_v3.live import EXPECTED_ROUTE_CONTRACT_HASH
from benchmarks.launch_burst_prospective_route_live_v4.replay_bound import (
    INCONCLUSIVE_CLASSIFICATION,
    PASS_CLASSIFICATION,
    run_bound,
)


class LaunchBurstV4WatermarkCapacityBoundTests(unittest.TestCase):
    def _write_json(self, path: Path, value) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def _fixture(self, root: Path, *, stop_reason: str = "prospective_timed_rotation"):
        source = root / "source"
        replay = root / "replay"
        raw = source / "raw-chunks" / "chunk-000001.jsonl"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(
            json.dumps({"type": "trace_header"})
            + "\n"
            + json.dumps(
                {
                    "type": "trace_footer",
                    "stop_reason": stop_reason,
                    "finalized_wall_ns": 120_000_000_000,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self._write_json(
            replay / "report.json",
            {
                "contract_hash_sha256": EXPECTED_ROUTE_CONTRACT_HASH,
                "provider_calls_enabled": False,
                "economic_outcomes_opened": False,
                "metrics": {"total_service_ms": {"max": 600.0}},
            },
        )
        self._write_json(
            replay / "systems-observations.json",
            {
                "observations": [
                    {
                        "selected": True,
                        "token_mint": "MINT_A",
                        "decision_cutoff_wall_ns": 115_100_000_000,
                        "entry_ready_at": 118,
                        "entry_deadline_at": 123,
                    }
                ]
            },
        )
        return source, replay

    def test_conservative_bound_passes_when_full_tick_plus_max_service_meets_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            source, replay = self._fixture(Path(directory))
            report = run_bound(
                source_run=source,
                capacity_replay_run=replay,
                rotation_seconds=1.0,
            )
        self.assertEqual(report["classification"], PASS_CLASSIFICATION)
        self.assertEqual(report["conservative_dispatch_lag_ms"], 1600.0)
        self.assertEqual(report["selected_count"], 1)
        self.assertEqual(report["selected_missed_entry_ready"], 0)
        self.assertEqual(report["selected_missed_deadline"], 0)
        self.assertFalse(report["provider_calls_enabled"])
        self.assertFalse(report["economic_outcomes_opened"])

    def test_size_rotation_makes_bound_inconclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            source, replay = self._fixture(Path(directory), stop_reason="chunk_rotation")
            report = run_bound(
                source_run=source,
                capacity_replay_run=replay,
                rotation_seconds=1.0,
            )
        self.assertEqual(report["classification"], INCONCLUSIVE_CLASSIFICATION)
        self.assertFalse(report["gates"]["historical_size_rotations_zero"])


if __name__ == "__main__":
    unittest.main()
