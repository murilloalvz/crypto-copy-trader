import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.helius_standard_wss_shadow_v0.pumpswap_pool_lookup_latency_probe import (
    _percentile,
    observed_pumpswap_pools,
    run_probe,
)


class PumpSwapPoolLookupLatencyProbeV0Tests(unittest.TestCase):
    def test_percentile_interpolation(self):
        values = [10.0, 20.0, 30.0, 40.0]
        self.assertEqual(_percentile(values, 50), 25.0)
        self.assertAlmostEqual(_percentile(values, 95), 38.5)

    def test_observed_pool_extraction_is_exact_and_deduped(self):
        rows = [
            {"type": "carbon_canonical_event", "status": "decoded", "event_type": "pumpswap_buy", "pool": "B"},
            {"type": "carbon_canonical_event", "status": "decoded", "event_type": "pumpswap_sell", "pool": "A"},
            {"type": "carbon_canonical_event", "status": "decoded", "event_type": "pumpswap_buy", "pool": "A"},
            {"type": "carbon_canonical_event", "status": "decoded", "event_type": "pump_trade", "pool": "IGNORED"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "carbon.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            self.assertEqual(observed_pumpswap_pools(path), ("A", "B"))

    def test_probe_writes_existing_decoder_contract(self):
        carbon_rows = [
            {"type": "carbon_canonical_event", "status": "decoded", "event_type": "pumpswap_buy", "pool": "POOL"}
        ]
        response = {
            "jsonrpc": "2.0",
            "result": {
                "context": {"slot": 123},
                "value": {
                    "owner": "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
                    "lamports": 1,
                    "executable": False,
                    "rentEpoch": 0,
                    "space": 300,
                    "data": ["AAAA", "base64"],
                },
            },
            "id": 1,
        }

        def fake_post(_url, _payload, *, timeout_seconds):
            self.assertGreater(timeout_seconds, 0)
            return response

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            carbon_path = root / "carbon.jsonl"
            out_path = root / "out.jsonl"
            carbon_path.write_text("".join(json.dumps(row) + "\n" for row in carbon_rows), encoding="utf-8")
            report = run_probe(
                carbon_output_path=carbon_path,
                output_path=out_path,
                api_key="test",
                rps=1000.0,
                post_json=fake_post,
            )
            rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()]

        self.assertTrue(report["valid_latency_probe"])
        self.assertEqual(report["requested_pools"], 1)
        self.assertEqual(report["accounts_found"], 1)
        self.assertEqual(report["request_errors"], 0)
        self.assertEqual(rows[0]["type"], "pumpswap_pool_account_probe")
        self.assertEqual(rows[0]["pool"], "POOL")
        self.assertEqual(rows[0]["rpc_context_slot"], 123)
        self.assertIn("lookup_latency_ms", rows[0])
        self.assertFalse(rows[0]["causal_for_source_shadow"])


if __name__ == "__main__":
    unittest.main()
