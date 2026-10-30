import unittest

from src.wallet_exit_context import (
    ExitCycleSeed,
    analyze_exit_context,
    extract_exit_cycle_seeds,
    summarize_exit_context,
)


def candle(timestamp, close, *, high=None, low=None):
    return {
        "timestamp": timestamp,
        "open": close,
        "high": close if high is None else high,
        "low": close if low is None else low,
        "close": close,
    }


class WalletExitContextTests(unittest.TestCase):
    def test_extracts_first_cycle_and_stops_before_reentry(self):
        swaps = [
            {"token_mint": "A", "block_time": 100, "token_change": 10, "dex": "PumpSwap"},
            {"token_mint": "A", "block_time": 200, "token_change": -3, "dex": "PumpSwap"},
            {"token_mint": "A", "block_time": 300, "token_change": -7, "dex": "PumpSwap"},
            {"token_mint": "A", "block_time": 400, "token_change": 5, "dex": "Jupiter v6"},
            {"token_mint": "A", "block_time": 500, "token_change": -5, "dex": "Jupiter v6"},
            {"token_mint": "B", "block_time": 50, "token_change": -1, "dex": "PumpSwap"},
            {"token_mint": "B", "block_time": 150, "token_change": 1, "dex": "PumpSwap"},
            {"token_mint": "B", "block_time": 250, "token_change": -1, "dex": "PumpSwap"},
            {"token_mint": "C", "block_time": 100, "token_change": 1, "dex": "Meteora DLMM"},
            {"token_mint": "D", "block_time": 100, "token_change": -1, "dex": "Orca Whirlpool"},
        ]
        result = extract_exit_cycle_seeds(swaps)
        self.assertEqual(result.token_count, 4)
        self.assertEqual(len(result.cycles), 1)
        cycle = result.cycles[0]
        self.assertEqual(cycle.token_mint, "A")
        self.assertEqual(cycle.first_sell_at, 200)
        self.assertEqual(cycle.last_sell_at, 300)
        self.assertEqual(cycle.sell_count, 2)
        self.assertEqual(cycle.reentry_at, 400)
        self.assertEqual(result.excluded_preexisting_inventory_token_count, 1)
        self.assertEqual(result.no_sell_after_buy_token_count, 1)
        self.assertEqual(result.no_observed_buy_token_count, 1)

    def test_analyzes_sell_returns_and_conservative_pre_exit_path(self):
        seed = ExitCycleSeed(
            "token", entry_at=100, first_sell_at=10_800, last_sell_at=14_400,
            sell_count=2, entry_dex="PumpSwap",
        )
        hourly = [
            candle(3_600, 110, high=130, low=90),
            candle(7_200, 120, high=150, low=80),
            candle(10_800, 999, high=999, low=1),
        ]
        result = analyze_exit_context(
            seed,
            entry_price_usd=100,
            first_sell_price_usd=120,
            last_sell_price_usd=110,
            pre_first_sell_hourly_candles=hourly,
        )
        self.assertAlmostEqual(result.first_sell_return_pct, 20.0)
        self.assertAlmostEqual(result.last_sell_return_pct, 10.0)
        self.assertAlmostEqual(result.first_to_last_sell_change_pct, -8.3333333333)
        self.assertAlmostEqual(result.mfe_before_first_sell_pct, 50.0)
        self.assertAlmostEqual(result.mae_before_first_sell_pct, -20.0)
        self.assertAlmostEqual(result.first_sell_vs_pre_exit_peak_pct, -20.0)
        self.assertTrue(result.path_complete_before_first_sell)

    def test_marks_truncated_hourly_path_as_partial(self):
        seed = ExitCycleSeed(
            "token", entry_at=100, first_sell_at=10_800, last_sell_at=10_800,
            sell_count=1, entry_dex="PumpSwap",
        )
        result = analyze_exit_context(
            seed,
            entry_price_usd=100,
            first_sell_price_usd=105,
            last_sell_price_usd=105,
            pre_first_sell_hourly_candles=[candle(7_200, 102, high=110, low=95)],
        )
        self.assertFalse(result.path_complete_before_first_sell)
        self.assertAlmostEqual(result.mfe_before_first_sell_pct, 10.0)

    def test_rejects_invalid_temporal_order(self):
        seed = ExitCycleSeed(
            "token", entry_at=200, first_sell_at=100, last_sell_at=300,
            sell_count=1, entry_dex=None,
        )
        with self.assertRaises(ValueError):
            analyze_exit_context(
                seed,
                entry_price_usd=1,
                first_sell_price_usd=2,
                last_sell_price_usd=2,
            )

    def test_summary_separates_multi_sell_reentry_and_complete_paths(self):
        first = analyze_exit_context(
            ExitCycleSeed(
                "A", entry_at=0, first_sell_at=7_200, last_sell_at=10_800,
                sell_count=2, entry_dex="PumpSwap", reentry_at=20_000,
            ),
            entry_price_usd=100,
            first_sell_price_usd=130,
            last_sell_price_usd=120,
            pre_first_sell_hourly_candles=[candle(3_600, 120, high=140, low=90)],
        )
        second = analyze_exit_context(
            ExitCycleSeed(
                "B", entry_at=0, first_sell_at=7_200, last_sell_at=7_200,
                sell_count=1, entry_dex="Jupiter v6",
            ),
            entry_price_usd=100,
            first_sell_price_usd=80,
            last_sell_price_usd=80,
            pre_first_sell_hourly_candles=[candle(3_600, 90, high=105, low=75)],
        )
        summary = summarize_exit_context([first, second], attempted_cycles=3)
        self.assertEqual(summary.priced_cycles, 2)
        self.assertEqual(summary.failed_cycles, 1)
        self.assertEqual(summary.positive_first_sell_share_pct, 50.0)
        self.assertEqual(summary.first_sell_up_20_share_pct, 50.0)
        self.assertEqual(summary.negative_first_sell_share_pct, 50.0)
        self.assertEqual(summary.multi_sell_cycle_share_pct, 50.0)
        self.assertEqual(summary.reentry_after_cycle_share_pct, 50.0)
        self.assertEqual(summary.path_complete_share_pct, 100.0)
        self.assertAlmostEqual(summary.median_mfe_before_first_sell_pct, 22.5)


if __name__ == "__main__":
    unittest.main()
