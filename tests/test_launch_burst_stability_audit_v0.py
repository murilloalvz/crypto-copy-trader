import unittest

from benchmarks.launch_burst_stability_audit_v0.run import (
    _comparison,
    _distribution,
    _feature_value,
)


class LaunchBurstStabilityAuditV0Tests(unittest.TestCase):
    def test_derived_features_are_outcome_blind_and_dimensionless(self):
        snapshot = {
            "event_count": 4,
            "buy_count": 3,
            "sell_count": 1,
            "count_buy_share_pct": 75.0,
            "unique_wallet_count": 2,
            "unique_transaction_count": 4,
        }
        self.assertEqual(_feature_value(snapshot, "event_rate_per_second", window_seconds=5), 0.8)
        self.assertEqual(_feature_value(snapshot, "net_buy_imbalance_pct", window_seconds=5), 50.0)
        self.assertEqual(_feature_value(snapshot, "wallets_per_event", window_seconds=5), 0.5)
        self.assertEqual(_feature_value(snapshot, "transactions_per_event", window_seconds=5), 1.0)

    def test_zero_event_ratios_are_explicit_missing(self):
        snapshot = {
            "event_count": 0,
            "buy_count": 0,
            "sell_count": 0,
            "count_buy_share_pct": None,
            "unique_wallet_count": 0,
            "unique_transaction_count": 0,
        }
        self.assertIsNone(_feature_value(snapshot, "net_buy_imbalance_pct", window_seconds=5))
        self.assertIsNone(_feature_value(snapshot, "wallets_per_event", window_seconds=5))
        self.assertIsNone(_feature_value(snapshot, "transactions_per_event", window_seconds=5))

    def test_distribution_and_comparison_do_not_invent_thresholds(self):
        a = _distribution([1, 2, 3])
        b = _distribution([2, 3, 4])
        result = _comparison(a, b)
        self.assertEqual(a["p50"], 2.0)
        self.assertEqual(b["p50"], 3.0)
        self.assertEqual(result["absolute_gap"], 1.0)
        self.assertEqual(result["b_over_a_ratio"], 1.5)
        self.assertNotIn("pass", result)
        self.assertNotIn("threshold", result)


if __name__ == "__main__":
    unittest.main()
