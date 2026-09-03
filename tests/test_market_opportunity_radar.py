import unittest

from src.market_opportunity_radar import (
    MARKET_OPPORTUNITY_RADAR_VERSION,
    MarketLifecycleObservation,
    MarketRadarConfig,
    MarketTradeObservation,
    build_market_movement_features,
    detect_market_movement,
)


class MarketOpportunityRadarTests(unittest.TestCase):
    def _established_sample(self, *, side: str = "buy") -> list[MarketTradeObservation]:
        rows = [
            MarketTradeObservation("T", "buy", 800, 802, f"B{i}", 10.0, 1.0, "pump")
            for i in range(3)
        ]
        rows.extend(
            MarketTradeObservation(
                "T",
                side if i < 5 else "sell",
                975 + i * 4,
                976 + i * 4,
                f"F{i}",
                10.0,
                1.0 + i * 0.01,
                "pump",
            )
            for i in range(6)
        )
        return rows

    def test_established_market_activity_acceleration_triggers(self):
        trigger = detect_market_movement(
            self._established_sample(), token_mint="T", as_of=1000
        )
        self.assertIsNotNone(trigger)
        assert trigger is not None
        self.assertEqual(trigger.method_version, MARKET_OPPORTUNITY_RADAR_VERSION)
        self.assertEqual(trigger.trigger_kind, "activity_acceleration")
        self.assertEqual(trigger.features.fast_event_count, 6)
        self.assertEqual(trigger.features.baseline_event_count, 3)
        self.assertGreaterEqual(trigger.features.fast_unique_wallet_count, 4)
        self.assertGreaterEqual(trigger.features.activity_acceleration_ratio or 0, 3.0)

    def test_backfilled_old_trade_is_not_fresh_flow(self):
        rows = self._established_sample()
        rows.append(
            MarketTradeObservation("T", "buy", 900, 999, "LATE", 500.0, 9.0, "pump")
        )
        features = build_market_movement_features(rows, token_mint="T", as_of=1000)
        self.assertEqual(features.fast_event_count, 6)
        self.assertEqual(features.baseline_event_count, 4)
        self.assertNotEqual(features.last_price_usd, 9.0)

    def test_future_observed_trade_is_excluded_from_t0(self):
        rows = self._established_sample()
        rows.append(
            MarketTradeObservation("T", "buy", 999, 1005, "FUTURE", 1000.0, 8.0, "pump")
        )
        features = build_market_movement_features(rows, token_mint="T", as_of=1000)
        self.assertEqual(features.fast_event_count, 6)
        self.assertNotIn("FUTURE", {row.wallet_address for row in rows if row.observed_at <= 1000})

    def test_fresh_market_can_trigger_without_historical_baseline(self):
        rows = [
            MarketTradeObservation(
                "NEW", "buy", 975 + i * 4, 976 + i * 4, f"W{i}", 5.0, 1.0, "pump"
            )
            for i in range(6)
        ]
        lifecycle = MarketLifecycleObservation("NEW", 930, 935, "pump")
        trigger = detect_market_movement(
            rows, token_mint="NEW", as_of=1000, lifecycle=lifecycle
        )
        self.assertIsNotNone(trigger)
        assert trigger is not None
        self.assertEqual(trigger.trigger_kind, "fresh_market_burst")
        self.assertEqual(trigger.features.baseline_event_count, 0)
        self.assertEqual(trigger.features.market_age_seconds, 70)

    def test_old_market_without_baseline_does_not_use_fresh_market_escape(self):
        rows = [
            MarketTradeObservation(
                "OLD", "buy", 975 + i * 4, 976 + i * 4, f"W{i}", 5.0, 1.0, "pump"
            )
            for i in range(6)
        ]
        lifecycle = MarketLifecycleObservation("OLD", 100, 101, "pump")
        self.assertIsNone(
            detect_market_movement(rows, token_mint="OLD", as_of=1000, lifecycle=lifecycle)
        )

    def test_direction_is_descriptive_and_can_be_downward(self):
        rows = [
            MarketTradeObservation("D", "buy", 800, 801, f"B{i}", 10.0, 1.0, "pump")
            for i in range(3)
        ]
        rows.extend(
            MarketTradeObservation(
                "D", "sell", 975 + i * 4, 976 + i * 4, f"S{i}", 20.0, 1.0, "pump"
            )
            for i in range(6)
        )
        trigger = detect_market_movement(rows, token_mint="D", as_of=1000)
        self.assertIsNotNone(trigger)
        assert trigger is not None
        self.assertEqual(trigger.direction, "downward_pressure")

    def test_large_price_move_is_not_required_to_trigger(self):
        rows = self._established_sample()
        rows = [
            MarketTradeObservation(
                row.token_mint,
                row.side,
                row.chain_time,
                row.observed_at,
                row.wallet_address,
                row.notional_usd,
                1.0,
                row.venue,
            )
            for row in rows
        ]
        trigger = detect_market_movement(rows, token_mint="T", as_of=1000)
        self.assertIsNotNone(trigger)
        assert trigger is not None
        self.assertEqual(trigger.features.fast_return_pct, 0.0)

    def test_partial_coverage_stays_explicit_without_notional_imputation(self):
        rows = self._established_sample()
        damaged = list(rows)
        item = damaged[-1]
        damaged[-1] = MarketTradeObservation(
            item.token_mint,
            item.side,
            item.chain_time,
            item.observed_at,
            None,
            None,
            None,
            item.venue,
        )
        features = build_market_movement_features(damaged, token_mint="T", as_of=1000)
        self.assertIn("partial_wallet_identity_coverage", features.data_quality_flags)
        self.assertIn("partial_notional_coverage", features.data_quality_flags)
        self.assertIn("partial_price_coverage", features.data_quality_flags)
        self.assertIsNone(features.signed_notional_imbalance_pct)
        self.assertIsNone(features.fast_return_pct)

    def test_impossible_availability_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            build_market_movement_features(
                [MarketTradeObservation("T", "buy", 100, 99, "W")],
                token_mint="T",
                as_of=110,
            )

    def test_detector_has_no_trading_score_or_decision(self):
        trigger = detect_market_movement(
            self._established_sample(), token_mint="T", as_of=1000
        )
        self.assertIsNotNone(trigger)
        assert trigger is not None
        self.assertFalse(hasattr(trigger, "score"))
        self.assertFalse(hasattr(trigger, "buy"))
        self.assertFalse(hasattr(trigger, "decision"))

    def test_invalid_config_is_rejected(self):
        with self.assertRaises(ValueError):
            build_market_movement_features(
                [],
                token_mint="T",
                as_of=1000,
                config=MarketRadarConfig(fast_window_seconds=300, baseline_horizon_seconds=300),
            )


if __name__ == "__main__":
    unittest.main()
