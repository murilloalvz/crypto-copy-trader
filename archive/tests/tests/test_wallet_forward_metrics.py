import unittest

from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_metrics import (
    summarize_forward_wallet_latency,
    summarize_forward_wallet_latency_by_address,
)


class WalletForwardMetricsTests(unittest.TestCase):
    def test_summarizes_detection_lag_and_threshold_coverage(self):
        rows = [
            WalletActionObservation("A", "T1", "buy", 100, 110),
            WalletActionObservation("A", "T2", "sell", 100, 130),
            WalletActionObservation("B", "T3", "buy", 100, 160),
            WalletActionObservation("B", "T4", "buy", 100, 220),
        ]

        result = summarize_forward_wallet_latency(rows)

        self.assertEqual(result.observation_count, 4)
        self.assertEqual(result.wallet_count, 2)
        self.assertEqual(result.token_count, 4)
        self.assertEqual(result.buy_count, 3)
        self.assertEqual(result.sell_count, 1)
        self.assertEqual(result.median_lag_seconds, 45.0)
        self.assertEqual(result.min_lag_seconds, 10.0)
        self.assertEqual(result.max_lag_seconds, 120.0)
        self.assertEqual(result.within_15s_share_pct, 25.0)
        self.assertEqual(result.within_30s_share_pct, 50.0)
        self.assertEqual(result.within_60s_share_pct, 75.0)
        self.assertEqual(result.within_120s_share_pct, 100.0)

    def test_empty_sample_is_explicit(self):
        result = summarize_forward_wallet_latency([])

        self.assertEqual(result.observation_count, 0)
        self.assertIsNone(result.median_lag_seconds)
        self.assertIsNone(result.p95_lag_seconds)
        self.assertEqual(result.within_60s_share_pct, 0.0)

    def test_rejects_negative_lag(self):
        with self.assertRaises(ValueError):
            summarize_forward_wallet_latency(
                [WalletActionObservation("A", "T", "buy", 200, 100)]
            )

    def test_groups_latency_by_wallet(self):
        rows = [
            WalletActionObservation("A", "T1", "buy", 100, 110),
            WalletActionObservation("B", "T2", "buy", 100, 150),
            WalletActionObservation("B", "T3", "sell", 200, 260),
        ]

        grouped = summarize_forward_wallet_latency_by_address(rows)

        self.assertEqual(grouped["A"].median_lag_seconds, 10.0)
        self.assertEqual(grouped["B"].median_lag_seconds, 55.0)


if __name__ == "__main__":
    unittest.main()
