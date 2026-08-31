import unittest

from src.wallet_entry_context import EntrySeed
from src.wallet_holding_context import (
    analyze_holding_context,
    summarize_holding_context,
)


def candle(timestamp, close, *, high=None, low=None):
    return {
        "timestamp": timestamp,
        "open": close,
        "high": close if high is None else high,
        "low": close if low is None else low,
        "close": close,
    }


class WalletHoldingContextTests(unittest.TestCase):
    def test_measures_multi_day_returns_and_path_extremes(self):
        seed = EntrySeed("token", 3_600, "PumpSwap")
        hourly = [
            candle(7_200, 110, high=115, low=90),
            candle(25_200, 120, high=130, low=95),
            candle(90_000, 150, high=160, low=80),
            candle(176_400, 140, high=170, low=70),
            candle(262_800, 130, high=180, low=60),
        ]
        result = analyze_holding_context(seed, 100.0, hourly)
        self.assertAlmostEqual(result.post_6h_return_pct, 20.0)
        self.assertAlmostEqual(result.post_24h_return_pct, 50.0)
        self.assertAlmostEqual(result.post_48h_return_pct, 40.0)
        self.assertAlmostEqual(result.post_72h_return_pct, 30.0)
        self.assertAlmostEqual(result.mfe_24h_pct, 60.0)
        self.assertAlmostEqual(result.mae_24h_pct, -20.0)
        self.assertAlmostEqual(result.mfe_72h_pct, 80.0)
        self.assertAlmostEqual(result.mae_72h_pct, -40.0)

    def test_excludes_partial_entry_hour_from_mfe_mae(self):
        seed = EntrySeed("token", 3_900, "Jupiter v6")
        hourly = [
            candle(3_600, 100, high=999, low=1),
            candle(7_200, 105, high=110, low=95),
            candle(90_000, 120, high=125, low=90),
        ]
        result = analyze_holding_context(seed, 100.0, hourly)
        self.assertAlmostEqual(result.mfe_24h_pct, 25.0)
        self.assertAlmostEqual(result.mae_24h_pct, -10.0)

    def test_summary_reports_coverage_and_positive_share(self):
        first = analyze_holding_context(
            EntrySeed("A", 3_600, "PumpSwap"),
            100.0,
            [candle(90_000, 120), candle(262_800, 130)],
        )
        second = analyze_holding_context(
            EntrySeed("B", 3_600, "Meteora DLMM"),
            100.0,
            [candle(90_000, 70), candle(262_800, 80)],
        )
        summary = summarize_holding_context([first, second], attempted_entries=3)
        self.assertEqual(summary.priced_entries, 2)
        self.assertEqual(summary.failed_entries, 1)
        self.assertEqual(summary.positive_24h_share_pct, 50.0)
        self.assertEqual(summary.positive_72h_share_pct, 50.0)
        self.assertEqual(summary.drawdown_30_24h_share_pct, 50.0)


if __name__ == "__main__":
    unittest.main()
