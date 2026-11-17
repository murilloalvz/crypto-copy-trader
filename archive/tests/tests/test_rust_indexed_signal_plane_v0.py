from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from benchmarks.commodity_signal_plane_v0.benchmark import generate_synthetic_trace, load_trace
from benchmarks.integrated_market_signal_plane_v1.rust_suite import (
    _json_equivalent,
    _python_indexed_oracle,
)


class RustIndexedSignalPlaneV0Tests(unittest.TestCase):
    def test_json_equivalent_accepts_only_tiny_numeric_rounding(self):
        self.assertTrue(
            _json_equivalent(
                {"x": [1, 2.0, {"y": 3.00000000001}]},
                {"x": [1.0, 2, {"y": 3.0}]},
            )
        )
        self.assertTrue(
            _json_equivalent(
                {"venues": ("pump",), "flags": ("a", "b")},
                {"venues": ["pump"], "flags": ["a", "b"]},
            )
        )
        self.assertFalse(_json_equivalent({"x": 3.01}, {"x": 3.0}))

    def test_python_oracle_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            generate_synthetic_trace(out=path, events=1200, seed=68)
            _, records = load_trace(path)
            left, _, left_state = _python_indexed_oracle(records)
            right, _, right_state = _python_indexed_oracle(records)

        self.assertEqual(left, right)
        self.assertEqual(
            left_state.late_chain_time_inserts,
            right_state.late_chain_time_inserts,
        )


if __name__ == "__main__":
    unittest.main()
