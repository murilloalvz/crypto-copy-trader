import unittest

from src.wallet_strategy_lab import (
    build_wallet_strategy_fingerprint,
    summarize_wallet_strategy_lab,
)


def _swap(token: str, at: int, change: float, dex: str = "Jupiter v6") -> dict:
    return {
        "kind": "swap",
        "status": "success",
        "token_mint": token,
        "token_change": change,
        "block_time": at,
        "dex": dex,
    }


class WalletStrategyLabTests(unittest.TestCase):
    def test_identifies_staged_exit_behavior_from_complete_like_cycles(self):
        swaps = [
            _swap("A", 0, 100),
            _swap("A", 3_600, -50),
            _swap("A", 7_200, -50),
            _swap("B", 86_400, 100),
            _swap("B", 90_000, -25),
            _swap("B", 100_000, -75),
            _swap("C", 172_800, 100),
            _swap("C", 180_000, -100),
        ]

        result = build_wallet_strategy_fingerprint("wallet-staged", swaps)

        self.assertEqual(result.holding_bucket, "intraday")
        self.assertEqual(result.exit_bucket, "staged_exit_dominant")
        self.assertEqual(result.reentry_bucket, "rare_reentry")
        self.assertEqual(result.complete_like_sizing_count, 3)
        self.assertEqual(result.complete_multi_sell_count, 2)
        self.assertAlmostEqual(
            result.median_complete_multi_first_sell_fraction_pct, 37.5
        )
        self.assertAlmostEqual(result.median_complete_multi_runner_pct, 62.5)

    def test_identifies_single_exit_dominant_swing_sample(self):
        swaps = []
        for index in range(5):
            buy_at = index * 86_400
            swaps.extend(
                [
                    _swap(f"T{index}", buy_at, 100, "PumpSwap"),
                    _swap(f"T{index}", buy_at + 2 * 86_400, -100, "PumpSwap"),
                ]
            )

        result = build_wallet_strategy_fingerprint("wallet-single", swaps)

        self.assertEqual(result.holding_bucket, "swing")
        self.assertEqual(result.exit_bucket, "single_exit_dominant")
        self.assertEqual(result.complete_like_sizing_count, 5)
        self.assertEqual(result.complete_multi_sell_count, 0)
        self.assertEqual(result.dominant_dex, "PumpSwap")
        self.assertAlmostEqual(result.dominant_dex_share_pct, 100.0)

    def test_frequency_bucket_uses_active_day_median_not_gap_extrapolation(self):
        swaps = [
            _swap("A", 0, 100),
            _swap("A", 1, -100),
            _swap("B", 2, 100),
            _swap("B", 3, -100),
            _swap("C", 100 * 86_400, 100),
            _swap("C", 100 * 86_400 + 1, -100),
        ]

        result = build_wallet_strategy_fingerprint("bursty", swaps)

        self.assertLess(result.swaps_per_day, 1.0)
        self.assertEqual(result.frequency_rate_per_day, 3.0)
        self.assertEqual(result.frequency_basis, "median_active_day_swaps")
        self.assertEqual(result.frequency_bucket, "moderate")
        self.assertIn("calendar_frequency_differs_from_active_intensity", result.flags)

    def test_many_observed_swaps_on_active_day_remain_high_frequency(self):
        swaps = [
            _swap(f"T{index}", index * 10, 100 if index % 2 == 0 else -100)
            for index in range(30)
        ]

        result = build_wallet_strategy_fingerprint("busy-day", swaps)

        self.assertEqual(result.frequency_rate_per_day, 30.0)
        self.assertEqual(result.frequency_basis, "median_active_day_swaps")
        self.assertEqual(result.frequency_bucket, "high_frequency")

    def test_small_or_empty_sample_is_marked_as_insufficient_not_invented(self):
        result = build_wallet_strategy_fingerprint("empty", [])

        self.assertEqual(result.holding_bucket, "holding_unknown")
        self.assertEqual(result.exit_bucket, "exit_sizing_insufficient")
        self.assertIn("onchain_sample_too_small", result.flags)
        self.assertIn("exit_sizing_sample_too_small", result.flags)

    def test_cross_wallet_summary_counts_strategy_dimensions(self):
        staged = build_wallet_strategy_fingerprint(
            "staged",
            [
                _swap("A", 0, 100),
                _swap("A", 3_600, -50),
                _swap("A", 7_200, -50),
                _swap("B", 86_400, 100),
                _swap("B", 90_000, -25),
                _swap("B", 100_000, -75),
                _swap("C", 172_800, 100),
                _swap("C", 180_000, -100),
            ],
        )
        empty = build_wallet_strategy_fingerprint("empty", [])

        summary = summarize_wallet_strategy_lab([staged, empty])

        self.assertEqual(summary.wallet_count, 2)
        self.assertEqual(summary.exit_buckets["staged_exit_dominant"], 1)
        self.assertEqual(summary.exit_buckets["exit_sizing_insufficient"], 1)
        self.assertEqual(sum(summary.signatures.values()), 2)


if __name__ == "__main__":
    unittest.main()
