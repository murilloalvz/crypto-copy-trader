import unittest

from src.market_opportunity_radar import (
    MarketLifecycleObservation,
    MarketTradeObservation,
    build_market_movement_features,
    detect_market_movement,
)


class MarketRadarTransactionAwarenessTests(unittest.TestCase):
    def _fresh_rows(self, transaction_keys: list[str | None]) -> list[MarketTradeObservation]:
        return [
            MarketTradeObservation(
                token_mint="T",
                side="buy",
                chain_time=975 + i * 4,
                observed_at=976 + i * 4,
                wallet_address=f"W{i}",
                venue="pump_bonding_curve",
                transaction_key=transaction_keys[i],
            )
            for i in range(6)
        ]

    def test_one_multi_event_transaction_cannot_satisfy_transaction_breadth(self):
        rows = self._fresh_rows(["sig-one"] * 6)
        lifecycle = MarketLifecycleObservation("T", 930, 935, "pump_bonding_curve")
        trigger = detect_market_movement(rows, token_mint="T", as_of=1000, lifecycle=lifecycle)
        self.assertIsNone(trigger)
        features = build_market_movement_features(rows, token_mint="T", as_of=1000, lifecycle=lifecycle)
        self.assertEqual(features.fast_event_count, 6)
        self.assertEqual(features.fast_unique_wallet_count, 6)
        self.assertEqual(features.fast_unique_transaction_count, 1)
        self.assertEqual(features.transaction_identity_coverage_pct, 100.0)

    def test_four_independent_transactions_can_satisfy_fresh_breadth(self):
        rows = self._fresh_rows(["a", "a", "b", "c", "d", "d"])
        lifecycle = MarketLifecycleObservation("T", 930, 935, "pump_bonding_curve")
        trigger = detect_market_movement(rows, token_mint="T", as_of=1000, lifecycle=lifecycle)
        self.assertIsNotNone(trigger)
        assert trigger is not None
        self.assertEqual(trigger.trigger_kind, "fresh_market_burst")
        self.assertEqual(trigger.features.fast_unique_transaction_count, 4)

    def test_missing_transaction_identity_stays_explicit_without_breaking_legacy_sources(self):
        rows = self._fresh_rows([None] * 6)
        lifecycle = MarketLifecycleObservation("T", 930, 935, "pump")
        features = build_market_movement_features(rows, token_mint="T", as_of=1000, lifecycle=lifecycle)
        self.assertIn("transaction_identity_missing", features.data_quality_flags)
        self.assertIsNone(features.fast_unique_transaction_count)
        self.assertIsNone(features.transaction_identity_coverage_pct)
        self.assertIsNotNone(detect_market_movement(rows, token_mint="T", as_of=1000, lifecycle=lifecycle))


if __name__ == "__main__":
    unittest.main()
