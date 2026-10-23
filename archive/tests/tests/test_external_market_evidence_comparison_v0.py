import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.helius_standard_wss_shadow_v0.compare_external_market_evidence import (
    compare_external_market_evidence,
)


class ExternalMarketEvidenceComparisonV0Tests(unittest.TestCase):
    def test_comparison_reports_coverage_without_creating_score(self):
        adapter = [
            {
                "type": "helius_standard_wss_shadow_adapter_result",
                "stage": "matched_unit_flow",
                "status": "ADAPTED",
                "observation": {
                    "token_mint": "A",
                    "side": "buy",
                    "venue": "pump",
                    "observed_at": 100,
                },
            },
            {
                "type": "helius_standard_wss_shadow_adapter_result",
                "stage": "matched_unit_flow",
                "status": "ADAPTED",
                "observation": {
                    "token_mint": "B",
                    "side": "sell",
                    "venue": "pumpswap",
                    "observed_at": 101,
                },
            },
        ]
        jupiter = [
            {
                "type": "jupiter_token_intelligence_observation",
                "mint": "A",
                "received_wall_ns": 1000,
                "payload": {"organicScore": 50, "holderCount": 20},
            }
        ]
        dex = [
            {
                "type": "dexscreener_market_evidence_observation",
                "pair_address": "PAIR_LOW",
                "matched_requested_mints": ["A"],
                "received_wall_ns": 2000,
                "payload": {"liquidity": {"usd": 10}, "volume": {"h24": 1}},
            },
            {
                "type": "dexscreener_market_evidence_observation",
                "pair_address": "PAIR_HIGH",
                "matched_requested_mints": ["A"],
                "received_wall_ns": 2001,
                "payload": {"liquidity": {"usd": 100}, "volume": {"h24": 2}},
            },
            {
                "type": "dexscreener_market_evidence_observation",
                "pair_address": "PAIR_B",
                "matched_requested_mints": ["B"],
                "received_wall_ns": 2002,
                "payload": {"liquidity": {"usd": 30}},
            },
        ]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter_path = root / "adapter.jsonl"
            jupiter_path = root / "jupiter.jsonl"
            dex_path = root / "dex.jsonl"
            out = root / "per-mint.jsonl"
            adapter_path.write_text("".join(json.dumps(row) + "\n" for row in adapter), encoding="utf-8")
            jupiter_path.write_text("".join(json.dumps(row) + "\n" for row in jupiter), encoding="utf-8")
            dex_path.write_text("".join(json.dumps(row) + "\n" for row in dex), encoding="utf-8")

            report = compare_external_market_evidence(
                adapter_path=adapter_path,
                jupiter_path=jupiter_path,
                dexscreener_path=dex_path,
                per_mint_out=out,
            )
            rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

        self.assertTrue(report["valid_comparison"])
        self.assertEqual(report["native_adapted_mints"], 2)
        self.assertEqual(report["jupiter_exact_mints"], 1)
        self.assertEqual(report["dexscreener_exact_mints"], 2)
        self.assertEqual(report["both_external_sources"], 1)
        self.assertEqual(report["dexscreener_only"], 1)
        self.assertFalse(report["score_or_recommendation_created"])
        a = next(row for row in rows if row["mint"] == "A")
        self.assertEqual(a["jupiter"]["organicScore"], 50)
        self.assertEqual(a["dexscreener"]["deepest_pair_address"], "PAIR_HIGH")
        self.assertEqual(a["dexscreener"]["pair_count"], 2)
        self.assertFalse(a["causal_for_source_shadow"])

    def test_jupiter_duplicate_mint_rows_fail_comparison(self):
        adapter = [
            {
                "type": "helius_standard_wss_shadow_adapter_result",
                "stage": "matched_unit_flow",
                "status": "ADAPTED",
                "observation": {"token_mint": "A", "side": "buy", "venue": "pump"},
            }
        ]
        duplicate = {
            "type": "jupiter_token_intelligence_observation",
            "mint": "A",
            "payload": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ap = root / "a.jsonl"
            jp = root / "j.jsonl"
            dp = root / "d.jsonl"
            out = root / "o.jsonl"
            ap.write_text(json.dumps(adapter[0]) + "\n", encoding="utf-8")
            jp.write_text(json.dumps(duplicate) + "\n" + json.dumps(duplicate) + "\n", encoding="utf-8")
            dp.write_text("", encoding="utf-8")
            report = compare_external_market_evidence(
                adapter_path=ap,
                jupiter_path=jp,
                dexscreener_path=dp,
                per_mint_out=out,
            )
        self.assertFalse(report["valid_comparison"])
        self.assertEqual(report["jupiter_duplicate_mint_rows_rejected"], 1)


if __name__ == "__main__":
    unittest.main()
