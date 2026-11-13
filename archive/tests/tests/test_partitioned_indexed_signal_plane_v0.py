from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from benchmarks.commodity_signal_plane_v0.benchmark import generate_synthetic_trace, load_trace
from benchmarks.integrated_market_signal_plane_v1.partitioned_suite import (
    _shard_for_token,
    run_partitioned,
)


class PartitionedIndexedSignalPlaneV0Tests(unittest.TestCase):
    def test_shard_assignment_is_deterministic(self):
        token = "TokenMint1111111111111111111111111111111"
        self.assertEqual(_shard_for_token(token, 4), _shard_for_token(token, 4))
        self.assertIn(_shard_for_token(token, 4), range(4))

    def test_partitioning_preserves_detector_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            generate_synthetic_trace(out=path, events=1200, seed=68)
            _, records = load_trace(path)
            report = run_partitioned(records, (1, 2, 4))

        for item in report["results"].values():
            self.assertEqual(item["detector_parity_pct"], 100.0)
            self.assertEqual(item["mismatches"], [])
            self.assertTrue(item["checks"]["parity_100"])


if __name__ == "__main__":
    unittest.main()
