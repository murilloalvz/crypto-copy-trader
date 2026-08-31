import unittest

from src.onchain_wallet_research import build_onchain_wallet_profile


class OnchainWalletExitShapeTests(unittest.TestCase):
    def test_multi_sell_without_reentry_tracks_sell_spacing(self):
        swaps = [
            {"block_time": 100, "status": "success", "kind": "swap", "dex": "PumpSwap", "token_mint": "A", "token_change": 10},
            {"block_time": 200, "status": "success", "kind": "swap", "dex": "PumpSwap", "token_mint": "A", "token_change": -3},
            {"block_time": 7_400, "status": "success", "kind": "swap", "dex": "PumpSwap", "token_mint": "A", "token_change": -7},
        ]
        profile = build_onchain_wallet_profile("wallet", swaps)
        self.assertEqual(profile.partial_exit_token_share_pct, 100.0)
        self.assertEqual(profile.multi_sell_without_reentry_token_share_pct, 100.0)
        self.assertEqual(profile.reentry_token_share_pct, 0.0)
        self.assertEqual(profile.median_same_token_sell_gap_seconds, 7_200.0)
        self.assertEqual(profile.same_token_sell_gap_over_1h_share_pct, 100.0)

    def test_reentry_is_separated_from_multi_sell_without_reentry(self):
        swaps = [
            {"block_time": 100, "status": "success", "kind": "swap", "dex": "Jupiter v6", "token_mint": "A", "token_change": 10},
            {"block_time": 200, "status": "success", "kind": "swap", "dex": "Jupiter v6", "token_mint": "A", "token_change": -5},
            {"block_time": 500, "status": "success", "kind": "swap", "dex": "Jupiter v6", "token_mint": "A", "token_change": 4},
            {"block_time": 600, "status": "success", "kind": "swap", "dex": "Jupiter v6", "token_mint": "A", "token_change": -9},
        ]
        profile = build_onchain_wallet_profile("wallet", swaps)
        self.assertEqual(profile.partial_exit_token_share_pct, 100.0)
        self.assertEqual(profile.multi_sell_without_reentry_token_share_pct, 0.0)
        self.assertEqual(profile.reentry_token_share_pct, 100.0)
        self.assertEqual(profile.median_reentry_gap_seconds, 300.0)
        self.assertEqual(profile.median_same_token_sell_gap_seconds, 400.0)
        self.assertEqual(profile.same_token_sell_gap_over_1h_share_pct, 0.0)


if __name__ == "__main__":
    unittest.main()
