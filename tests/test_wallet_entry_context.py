import unittest

from src.wallet_entry_context import (
    EntrySeed,
    analyze_entry_candles,
    summarize_entry_context,
)


def candle(timestamp, close, *, high=None, low=None):
    return {
        "timestamp": timestamp,
        "open": close,
        "high": close if high is None else high,
        "low": close if low is None else low,
        "close": close,
    }


class WalletEntryContextTests(unittest.TestCase):
    def test_detects_momentum_breakout_like_context(self):
        seed = EntrySeed("token", 3_600, "PumpSwap")
        candles = [
            candle(0, 80, high=90, low=75),
            candle(2_700, 100, high=102, low=98),
            candle(3_300, 112, high=114, low=110),
            candle(3_600, 120, high=121, low=118),
            candle(3_900, 126),
            candle(4_500, 132),
            candle(7_200, 144),
        ]
        result = analyze_entry_candles(seed, candles)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.pre_15m_return_pct, 20.0)
        self.assertAlmostEqual(result.pre_60m_return_pct, 50.0)
        self.assertEqual(result.context_label, "momentum_breakout_like")
        self.assertGreaterEqual(result.pre_60m_range_position_pct, 70.0)
        self.assertAlmostEqual(result.post_60m_return_pct, 20.0)

    def test_detects_dip_like_context_without_using_future_return(self):
        seed = EntrySeed("token", 3_600, "Jupiter v6")
        candles = [
            candle(0, 125, high=130, low=123),
            candle(2_700, 120, high=122, low=118),
            candle(3_300, 95, high=98, low=92),
            candle(3_600, 90, high=92, low=85),
            candle(3_900, 180),
            candle(4_500, 200),
            candle(7_200, 250),
        ]
        result = analyze_entry_candles(seed, candles)
        self.assertIsNotNone(result)
        self.assertEqual(result.context_label, "dip_like")
        self.assertLessEqual(result.pre_60m_range_position_pct, 30.0)
        self.assertGreater(result.post_60m_return_pct, 100.0)

    def test_summary_keeps_failed_entries_and_reports_distribution(self):
        first = analyze_entry_candles(
            EntrySeed("A", 3_600, "PumpSwap"),
            [
                candle(0, 80, high=90, low=75),
                candle(2_700, 100),
                candle(3_300, 110),
                candle(3_600, 120, high=121, low=118),
                candle(3_900, 121),
                candle(4_500, 122),
                candle(7_200, 123),
            ],
        )
        second = analyze_entry_candles(
            EntrySeed("B", 3_600, "Jupiter v6"),
            [
                candle(0, 125, high=130, low=123),
                candle(2_700, 120),
                candle(3_300, 95),
                candle(3_600, 90, high=92, low=85),
                candle(3_900, 91),
                candle(4_500, 92),
                candle(7_200, 93),
            ],
        )
        summary = summarize_entry_context([first, second], attempted_entries=3)
        self.assertEqual(summary.priced_entries, 2)
        self.assertEqual(summary.failed_entries, 1)
        self.assertEqual(summary.dex_mix["PumpSwap"], 1)
        self.assertEqual(summary.dex_mix["Jupiter v6"], 1)
        self.assertEqual(summary.pre15_up_5_share_pct, 50.0)
        self.assertEqual(summary.pre15_down_5_share_pct, 50.0)


if __name__ == "__main__":
    unittest.main()
