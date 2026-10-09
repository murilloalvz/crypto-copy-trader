import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.helius_standard_wss_shadow_v0.jupiter_token_intelligence_probe import (
    exact_mints_from_adapter,
    probe_jupiter_token_intelligence,
)


class JupiterTokenIntelligenceProbeV0Tests(unittest.TestCase):
    def test_exact_mints_only_from_adapted_flow_rows(self):
        rows = [
            {
                "type": "helius_standard_wss_shadow_adapter_result",
                "stage": "matched_unit_flow",
                "status": "ADAPTED",
                "observation": {"token_mint": "MINT_B"},
            },
            {
                "type": "helius_standard_wss_shadow_adapter_result",
                "stage": "matched_unit_flow",
                "status": "ADAPTED",
                "observation": {"token_mint": "MINT_A"},
            },
            {
                "type": "helius_standard_wss_shadow_adapter_result",
                "stage": "matched_unit_flow",
                "status": "MISSING_CONTEXT",
                "observation": {"token_mint": "SHOULD_NOT_APPEAR"},
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "adapter.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            self.assertEqual(exact_mints_from_adapter(path), ("MINT_A", "MINT_B"))

    def test_probe_keeps_provider_fields_native_and_ignores_unrequested_results(self):
        adapter_rows = [
            {
                "type": "helius_standard_wss_shadow_adapter_result",
                "stage": "matched_unit_flow",
                "status": "ADAPTED",
                "observation": {"token_mint": "MINT_A"},
            }
        ]

        def fake_get_json(url, *, api_key, timeout_seconds):
            self.assertIn("MINT_A", url)
            self.assertIsNone(api_key)
            return [
                {
                    "id": "MINT_A",
                    "organicScore": 42.5,
                    "holderCount": 12,
                    "audit": {"isSus": True},
                    "stats5m": {"numBuys": 3},
                },
                {"id": "SYMBOL_MATCH_NO", "organicScore": 99},
            ]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = root / "adapter.jsonl"
            out = root / "jupiter.jsonl"
            adapter.write_text(
                "".join(json.dumps(row) + "\n" for row in adapter_rows), encoding="utf-8"
            )
            report = probe_jupiter_token_intelligence(
                adapter_path=adapter,
                output_path=out,
                api_key=None,
                rps=1000,
                get_json=fake_get_json,
            )
            saved = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

        self.assertTrue(report["valid_probe"])
        self.assertEqual(report["mints_requested"], 1)
        self.assertEqual(report["mints_returned_exact"], 1)
        self.assertEqual(report["field_coverage_counts"]["organicScore"], 1)
        self.assertFalse(report["external_score_is_ground_truth"])
        self.assertFalse(report["causal_for_source_shadow"])
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["payload"]["organicScore"], 42.5)
        self.assertTrue(saved[0]["payload"]["audit"]["isSus"])

    def test_missing_exact_mint_stays_missing(self):
        adapter_rows = [
            {
                "type": "helius_standard_wss_shadow_adapter_result",
                "stage": "matched_unit_flow",
                "status": "ADAPTED",
                "observation": {"token_mint": "MINT_A"},
            }
        ]

        def fake_get_json(_url, *, api_key, timeout_seconds):
            return []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = root / "adapter.jsonl"
            out = root / "jupiter.jsonl"
            adapter.write_text(
                "".join(json.dumps(row) + "\n" for row in adapter_rows), encoding="utf-8"
            )
            report = probe_jupiter_token_intelligence(
                adapter_path=adapter,
                output_path=out,
                rps=1000,
                get_json=fake_get_json,
            )
        self.assertTrue(report["valid_probe"])
        self.assertEqual(report["missing_mints"], 1)
        self.assertEqual(report["exact_mint_coverage_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
