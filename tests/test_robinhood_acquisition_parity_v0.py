import json
import tempfile
import unittest
from pathlib import Path

from benchmarks.robinhood_launch_burst_v0.acquisition_parity import compare_event_captures_v0


class RobinhoodAcquisitionParityV0Tests(unittest.TestCase):
    def row(self, observed_at_ns, quote=1000):
        return {
            "kind": "trade",
            "side": "BUY",
            "curve": "0x" + "22" * 20,
            "actor": "0x" + "33" * 20,
            "recipient": "0x" + "33" * 20,
            "quote_amount_raw": quote,
            "token_amount_raw": 5000,
            "fee_raw": 100,
            "tax_raw": 20,
            "block_number": 10,
            "transaction_index": 0,
            "log_index": 1,
            "transaction_hash": "0xtx",
            "block_hash": "0xblock",
            "observed_at_ns": observed_at_ns,
            "block_timestamp_s": 1000,
        }

    def write(self, path, rows):
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def test_observation_clock_may_differ_with_chain_payload_parity(self):
        with tempfile.TemporaryDirectory() as temporary:
            left = Path(temporary) / "left.jsonl"
            right = Path(temporary) / "right.jsonl"
            self.write(left, [self.row(1_000_000_000)])
            self.write(right, [self.row(900_000_000)])
            result = compare_event_captures_v0(left, right)
        self.assertEqual(result["classification"], "PASS_ROBINHOOD_ACQUISITION_CHAIN_PARITY_V0")
        self.assertEqual(result["common_coverage_pct"], 100.0)
        self.assertEqual(result["right_minus_left_observed_at_ms"]["p50"], -100.0)

    def test_payload_conflict_fails_parity(self):
        with tempfile.TemporaryDirectory() as temporary:
            left = Path(temporary) / "left.jsonl"
            right = Path(temporary) / "right.jsonl"
            self.write(left, [self.row(1_000_000_000, quote=1000)])
            self.write(right, [self.row(900_000_000, quote=2000)])
            result = compare_event_captures_v0(left, right)
        self.assertEqual(result["classification"], "FAIL_ROBINHOOD_ACQUISITION_CHAIN_PARITY_V0")
        self.assertFalse(result["gates"]["chain_payload_conflicts_zero"])


if __name__ == "__main__":
    unittest.main()
