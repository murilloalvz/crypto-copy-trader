import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.helius_standard_wss_shadow_v0.dexscreener_market_probe import (
    probe_dexscreener_market_evidence,
)


class DexScreenerMarketProbeV0Tests(unittest.TestCase):
    def _adapter(self, root: Path, mints: tuple[str, ...]) -> Path:
        path = root / "adapter.jsonl"
        rows = [
            {
                "type": "helius_standard_wss_shadow_adapter_result",
                "stage": "matched_unit_flow",
                "status": "ADAPTED",
                "observation": {"token_mint": mint},
            }
            for mint in mints
        ]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def test_exact_requested_solana_pair_is_retained(self):
        def fake_get_json(url, *, timeout_seconds):
            self.assertIn("MINT_A", url)
            return [
                {
                    "chainId": "solana",
                    "pairAddress": "PAIR",
                    "baseToken": {"address": "MINT_A"},
                    "quoteToken": {"address": "QUOTE"},
                    "liquidity": {"usd": 123.0},
                    "volume": {"h24": 456.0},
                    "txns": {"m5": {"buys": 2, "sells": 1}},
                    "priceUsd": "0.01",
                    "pairCreatedAt": 123456,
                    "boosts": {"active": 1},
                },
                {
                    "chainId": "ethereum",
                    "pairAddress": "WRONG_CHAIN",
                    "baseToken": {"address": "MINT_A"},
                    "quoteToken": {"address": "Q"},
                },
                {
                    "chainId": "solana",
                    "pairAddress": "OFF_REQUEST",
                    "baseToken": {"address": "OTHER"},
                    "quoteToken": {"address": "Q"},
                },
            ]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self._adapter(root, ("MINT_A",))
            out = root / "dex.jsonl"
            report = probe_dexscreener_market_evidence(
                adapter_path=adapter,
                output_path=out,
                rps=1000,
                get_json=fake_get_json,
            )
            saved = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

        self.assertTrue(report["valid_probe"])
        self.assertEqual(report["mints_with_exact_pair_match"], 1)
        self.assertEqual(report["pair_rows_saved"], 1)
        self.assertEqual(report["off_request_or_invalid_pairs_rejected"], 2)
        self.assertEqual(report["pair_field_coverage_counts"]["liquidity_usd"], 1)
        self.assertFalse(report["provider_market_metrics_are_ground_truth"])
        self.assertFalse(report["causal_for_source_shadow"])
        self.assertEqual(saved[0]["matched_requested_mints"], ["MINT_A"])

    def test_duplicate_pair_is_rejected_without_double_counting(self):
        def fake_get_json(_url, *, timeout_seconds):
            pair = {
                "chainId": "solana",
                "pairAddress": "PAIR",
                "baseToken": {"address": "MINT_A"},
                "quoteToken": {"address": "QUOTE"},
            }
            return [pair, dict(pair)]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self._adapter(root, ("MINT_A",))
            report = probe_dexscreener_market_evidence(
                adapter_path=adapter,
                output_path=root / "out.jsonl",
                rps=1000,
                get_json=fake_get_json,
            )
        self.assertEqual(report["pair_rows_saved"], 1)
        self.assertEqual(report["duplicate_pair_rows_rejected"], 1)

    def test_missing_pair_stays_missing(self):
        def fake_get_json(_url, *, timeout_seconds):
            return []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = self._adapter(root, ("MINT_A",))
            report = probe_dexscreener_market_evidence(
                adapter_path=adapter,
                output_path=root / "out.jsonl",
                rps=1000,
                get_json=fake_get_json,
            )
        self.assertTrue(report["valid_probe"])
        self.assertEqual(report["missing_mints"], 1)
        self.assertEqual(report["exact_mint_pair_coverage_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
