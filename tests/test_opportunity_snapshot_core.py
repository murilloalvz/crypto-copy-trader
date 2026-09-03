import unittest

from src.causal_quotes import CausalQuoteObservation
from src.opportunity_snapshot_core import (
    FlowTradeObservation,
    build_opportunity_snapshot_core_v1,
)


def quote(
    *,
    side: str,
    market_time: int,
    observed_at: int,
    price_usd: float,
    executable: bool = False,
    swap_usd_value: float | None = None,
) -> CausalQuoteObservation:
    return CausalQuoteObservation(
        token_mint="T",
        side=side,
        market_time=market_time,
        observed_at=observed_at,
        price_usd=price_usd,
        source="test",
        executable=executable,
        provider_router="router",
        provider_price_impact_pct_points=0.5,
        provider_swap_usd_value=swap_usd_value,
    )


class OpportunitySnapshotCoreTests(unittest.TestCase):
    def test_backfilled_chain_event_is_not_available_before_observed_at(self):
        flow = [
            FlowTradeObservation(
                token_mint="T",
                side="buy",
                chain_time=400,
                observed_at=1_000,
                wallet_address="A",
                notional_usd=10,
                price_usd=1,
            )
        ]

        snapshot = build_opportunity_snapshot_core_v1(
            token_mint="T",
            as_of=500,
            flow_observations=flow,
            flow_windows_seconds=(300,),
        )

        self.assertEqual(snapshot.flow_windows[0].event_count, 0)
        self.assertIn("no_flow_context", snapshot.data_quality_flags)

    def test_old_trade_observed_now_is_not_fresh_flow(self):
        flow = [
            # Available by T0, but market event is 500 seconds old. It must not be counted
            # in a 10-second flow window merely because it was hydrated recently.
            FlowTradeObservation("T", "buy", 500, 995, "A", 20, 1.0),
            FlowTradeObservation("T", "buy", 995, 999, "B", 10, 1.1),
        ]

        snapshot = build_opportunity_snapshot_core_v1(
            token_mint="T",
            as_of=1_000,
            flow_observations=flow,
            flow_windows_seconds=(10,),
        )

        features = snapshot.flow_windows[0]
        self.assertEqual(features.event_count, 1)
        self.assertEqual(features.unique_buy_wallet_count, 1)
        self.assertEqual(features.buy_notional_usd, 10)
        self.assertEqual(features.median_observation_lag_seconds, 4.0)

    def test_recent_trade_observed_after_t0_is_not_available(self):
        flow = [
            FlowTradeObservation("T", "buy", 995, 1_005, "A", 20, 1.0),
        ]

        snapshot = build_opportunity_snapshot_core_v1(
            token_mint="T",
            as_of=1_000,
            flow_observations=flow,
            flow_windows_seconds=(10,),
        )

        self.assertEqual(snapshot.flow_windows[0].event_count, 0)

    def test_flow_window_uses_market_time_after_availability_gate(self):
        flow = [
            FlowTradeObservation("T", "buy", 930, 940, "A", 20, 1.00),
            FlowTradeObservation("T", "buy", 945, 950, "A", 30, 1.10),
            FlowTradeObservation("T", "sell", 960, 970, "B", 10, 1.20),
            FlowTradeObservation("T", "buy", 980, 1_010, "C", 999, 99.0),
        ]

        snapshot = build_opportunity_snapshot_core_v1(
            token_mint="T",
            as_of=1_000,
            flow_observations=flow,
            flow_windows_seconds=(100,),
        )
        features = snapshot.flow_windows[0]

        self.assertEqual(features.event_count, 3)
        self.assertEqual(features.buy_count, 2)
        self.assertEqual(features.sell_count, 1)
        self.assertEqual(features.unique_buy_wallet_count, 1)
        self.assertEqual(features.unique_sell_wallet_count, 1)
        self.assertEqual(features.wallet_identity_coverage_pct, 100.0)
        self.assertEqual(features.notional_coverage_pct, 100.0)
        self.assertEqual(features.price_coverage_pct, 100.0)
        self.assertEqual(features.buy_notional_usd, 50)
        self.assertEqual(features.sell_notional_usd, 10)
        self.assertEqual(features.signed_notional_usd, 40)
        self.assertAlmostEqual(features.notional_imbalance_pct, 66.6666666667)
        self.assertAlmostEqual(features.repeated_wallet_event_share_pct, 33.3333333333)
        self.assertAlmostEqual(features.return_pct, 20.0)
        self.assertEqual(features.median_observation_lag_seconds, 10.0)
        self.assertEqual(features.max_observation_lag_seconds, 10)

    def test_partial_input_coverage_is_flagged_not_imputed(self):
        flow = [
            FlowTradeObservation("T", "buy", 950, 960, "A", 20, 1.0),
            FlowTradeObservation("T", "sell", 970, 980, None, None, None),
        ]

        snapshot = build_opportunity_snapshot_core_v1(
            token_mint="T",
            as_of=1_000,
            flow_observations=flow,
            flow_windows_seconds=(60,),
        )
        features = snapshot.flow_windows[0]

        self.assertEqual(features.wallet_identity_coverage_pct, 50.0)
        self.assertEqual(features.notional_coverage_pct, 50.0)
        self.assertEqual(features.price_coverage_pct, 50.0)
        self.assertIsNone(features.buy_notional_usd)
        self.assertIsNone(features.notional_imbalance_pct)
        self.assertIsNone(features.repeated_wallet_event_share_pct)
        self.assertIsNone(features.return_pct)
        self.assertIn("partial_notional_coverage", features.data_quality_flags)
        self.assertIn("partial_price_coverage", features.data_quality_flags)
        self.assertIn("partial_wallet_identity_coverage", features.data_quality_flags)

    def test_future_quote_is_excluded_and_quote_age_is_explicit(self):
        quotes = [
            quote(side="buy", market_time=980, observed_at=990, price_usd=1.1),
            quote(side="sell", market_time=995, observed_at=1_010, price_usd=1.2),
        ]

        snapshot = build_opportunity_snapshot_core_v1(
            token_mint="T",
            as_of=1_000,
            quotes=quotes,
        )

        self.assertEqual(snapshot.execution.quote_count, 1)
        self.assertEqual(snapshot.execution.buy_quote_count, 1)
        self.assertEqual(snapshot.execution.sell_quote_count, 0)
        self.assertEqual(snapshot.execution.latest_buy_price_usd, 1.1)
        self.assertEqual(snapshot.execution.latest_buy_observation_age_seconds, 10)
        self.assertEqual(snapshot.execution.latest_buy_market_age_seconds, 20)
        self.assertIsNone(snapshot.execution.latest_sell_price_usd)
        self.assertIn("sell_quote_unavailable", snapshot.execution.data_quality_flags)
        self.assertIn("proxy_quotes_only", snapshot.execution.data_quality_flags)

    def test_mixed_quote_notionals_are_visible_not_silently_combined(self):
        quotes = [
            quote(
                side="buy",
                market_time=980,
                observed_at=990,
                price_usd=1.1,
                swap_usd_value=25,
            ),
            quote(
                side="sell",
                market_time=985,
                observed_at=995,
                price_usd=1.0,
                swap_usd_value=100,
            ),
        ]

        snapshot = build_opportunity_snapshot_core_v1(
            token_mint="T",
            as_of=1_000,
            quotes=quotes,
        )

        self.assertEqual(snapshot.execution.quote_notional_min_usd, 25)
        self.assertEqual(snapshot.execution.quote_notional_max_usd, 100)
        self.assertIn("mixed_quote_notionals", snapshot.execution.data_quality_flags)

    def test_snapshot_has_no_score_or_trading_decision(self):
        snapshot = build_opportunity_snapshot_core_v1(token_mint="T", as_of=1_000)

        self.assertFalse(hasattr(snapshot, "score"))
        self.assertFalse(hasattr(snapshot, "decision"))
        self.assertEqual(
            snapshot.method_version,
            "opportunity_snapshot_core_v1_1_dual_clock",
        )

    def test_rejects_impossible_observation_timestamp(self):
        with self.assertRaises(ValueError):
            build_opportunity_snapshot_core_v1(
                token_mint="T",
                as_of=1_000,
                flow_observations=[
                    FlowTradeObservation("T", "buy", 200, 100, "A", 10, 1)
                ],
            )

    def test_flow_windows_must_be_unique_and_positive(self):
        with self.assertRaises(ValueError):
            build_opportunity_snapshot_core_v1(
                token_mint="T",
                as_of=1_000,
                flow_windows_seconds=(30, 30),
            )
        with self.assertRaises(ValueError):
            build_opportunity_snapshot_core_v1(
                token_mint="T",
                as_of=1_000,
                flow_windows_seconds=(0, 30),
            )


if __name__ == "__main__":
    unittest.main()
