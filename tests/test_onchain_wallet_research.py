import unittest

from src.onchain_wallet_research import build_onchain_wallet_profile


class OnchainWalletResearchTests(unittest.TestCase):
    def test_detects_scale_in_partial_exit_and_reentry(self):
        swaps = [
            {"block_time": 100, "status": "success", "kind": "swap", "dex": "Jupiter v6", "token_mint": "A", "token_change": 10},
            {"block_time": 120, "status": "success", "kind": "swap", "dex": "Jupiter v6", "token_mint": "A", "token_change": 5},
            {"block_time": 160, "status": "success", "kind": "swap", "dex": "Jupiter v6", "token_mint": "A", "token_change": -4},
            {"block_time": 180, "status": "success", "kind": "swap", "dex": "Jupiter v6", "token_mint": "A", "token_change": 2},
            {"block_time": 220, "status": "success", "kind": "swap", "dex": "Jupiter v6", "token_mint": "A", "token_change": -13},
        ]
        profile = build_onchain_wallet_profile("wallet", swaps)
        self.assertEqual(profile.swap_count, 5)
        self.assertEqual(profile.token_count, 1)
        self.assertEqual(profile.roundtrip_token_count, 1)
        self.assertEqual(profile.roundtrip_token_share_pct, 100.0)
        self.assertEqual(profile.scale_in_token_share_pct, 100.0)
        self.assertEqual(profile.partial_exit_token_share_pct, 100.0)
        self.assertEqual(profile.reentry_token_share_pct, 100.0)
        self.assertEqual(profile.median_first_exit_seconds, 60.0)
        self.assertEqual(profile.median_roundtrip_span_seconds, 120.0)

    def test_ignores_non_swap_and_failed_rows(self):
        swaps = [
            {"block_time": 100, "status": "failed", "kind": "swap", "dex": "Jupiter v6", "token_mint": "A", "token_change": 1},
            {"block_time": 110, "status": "success", "kind": "token_transfer", "dex": None, "token_mint": "A", "token_change": 1},
            {"block_time": 120, "status": "success", "kind": "swap", "dex": "PumpSwap", "token_mint": "B", "token_change": 1},
        ]
        profile = build_onchain_wallet_profile("wallet", swaps)
        self.assertEqual(profile.swap_count, 1)
        self.assertEqual(profile.buy_count, 1)
        self.assertEqual(profile.sell_count, 0)
        self.assertEqual(profile.buy_only_token_count, 1)
        self.assertIn("no_observed_sells", profile.flags)

    def test_multi_token_summary_is_not_overstated(self):
        swaps = [
            {"block_time": 100, "status": "success", "kind": "swap", "dex": "PumpSwap", "token_mint": "A", "token_change": 1},
            {"block_time": 200, "status": "success", "kind": "swap", "dex": "PumpSwap", "token_mint": "A", "token_change": -1},
            {"block_time": 300, "status": "success", "kind": "swap", "dex": "Raydium CPMM", "token_mint": "B", "token_change": 2},
            {"block_time": 400, "status": "success", "kind": "swap", "dex": "Raydium CPMM", "token_mint": "C", "token_change": 3},
        ]
        profile = build_onchain_wallet_profile("wallet", swaps)
        self.assertEqual(profile.token_count, 3)
        self.assertEqual(profile.roundtrip_token_count, 1)
        self.assertEqual(profile.buy_only_token_count, 2)
        self.assertAlmostEqual(profile.roundtrip_token_share_pct, 100 / 3)
        self.assertEqual(profile.dex_mix["PumpSwap"], 2)
        self.assertEqual(profile.dex_mix["Raydium CPMM"], 2)
        self.assertIn("many_tokens_without_observed_roundtrip", profile.flags)

    def test_sell_before_buy_is_not_counted_as_completed_roundtrip(self):
        swaps = [
            {"block_time": 100, "status": "success", "kind": "swap", "dex": "PumpSwap", "token_mint": "A", "token_change": -3},
            {"block_time": 200, "status": "success", "kind": "swap", "dex": "PumpSwap", "token_mint": "A", "token_change": 2},
        ]
        profile = build_onchain_wallet_profile("wallet", swaps)
        self.assertEqual(profile.token_count, 1)
        self.assertEqual(profile.roundtrip_token_count, 0)
        self.assertEqual(profile.sell_before_first_buy_token_count, 1)
        self.assertEqual(profile.roundtrip_token_share_pct, 0.0)
        self.assertIsNone(profile.median_first_exit_seconds)
        self.assertIn("preexisting_inventory_observed", profile.flags)
        self.assertIn("many_tokens_without_observed_roundtrip", profile.flags)


if __name__ == "__main__":
    unittest.main()
