import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.helius_standard_wss_shadow_v0.diagnose_invalid_matched_unit import diagnose


class InvalidMatchedUnitDiagnosticV0Tests(unittest.TestCase):
    def _write(self, path: Path, rows):
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def test_classifies_clock_and_nonpositive_reserve_without_changing_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            carbon = root / "carbon.jsonl"
            adapted = root / "adapted.jsonl"
            self._write(carbon, [
                {
                    "type": "carbon_canonical_event",
                    "event_key": "pump:1",
                    "event_type": "pump_trade",
                    "mint": "MINT",
                    "side": "buy",
                    "timestamp": 101,
                    "quote_mint": "QUOTE",
                    "quote_amount_raw": 10,
                    "virtual_quote_reserves_raw": 0,
                },
                {
                    "type": "carbon_canonical_event",
                    "event_key": "swap:1",
                    "event_type": "pumpswap_buy",
                    "pool": "POOL",
                    "side": "buy",
                    "timestamp": 102,
                    "quote_amount_raw": 5,
                    "pool_quote_token_reserves_raw": 100,
                },
            ])
            self._write(adapted, [
                {
                    "type": "helius_standard_wss_shadow_adapter_result",
                    "stage": "matched_unit_flow",
                    "status": "INVALID_EVENT",
                    "event_key": "pump:1",
                    "observed_at": 100,
                },
                {
                    "type": "helius_standard_wss_shadow_adapter_result",
                    "stage": "matched_unit_flow",
                    "status": "INVALID_EVENT",
                    "event_key": "swap:1",
                    "observed_at": 103,
                },
            ])
            report = diagnose(carbon_output=carbon, adapter_output=adapted)

        self.assertTrue(report["valid_diagnostic"])
        self.assertEqual(report["invalid_events"], 2)
        self.assertEqual(report["missing_carbon_events"], 0)
        self.assertEqual(report["reason_counts"]["quote_reserve_nonpositive_or_invalid"], 1)
        self.assertEqual(report["reason_counts"]["observed_before_chain_time"], 1)
        self.assertEqual(report["reason_counts_by_event_type"]["pump_trade"]["observed_before_chain_time"], 1)
        self.assertEqual(report["clock_delta_seconds"]["min"], -1)
        self.assertEqual(report["clock_delta_seconds"]["max"], 1)


if __name__ == "__main__":
    unittest.main()
