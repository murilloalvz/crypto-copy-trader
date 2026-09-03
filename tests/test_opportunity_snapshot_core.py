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
    )


class OpportunitySnapshotCoreTests(unittest.TestCase):
    def test_backfilled_chain_event_is_not_available_before_observed_at(self):
        flow = [
            FlowTradeObservation(
                token_mint="T",
                side="buy",
                chain_time=100,
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

    def test_flow_window_uses_observation_time_and_builds_descriptive_features(self):
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
        self.assertEqual(features.buy_notional_usd, 50)
        self.assertEqual(features.sell_notional_usd, 10)
        self.assertEqual(features.signed_notional_usd, 40)
        self.assertAlmostEqual(features.notional_imbalance_pct, 66.6666666667)
        self.assertAlmostEqual(features.repeated_wallet_event_share_pct, 33.3333333333)
        self.assertAlmostEqual(features.return_pct, 20.0)
        self.assertEqual(features.median_observation_lag_seconds, 10.0)

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

        self.assertIsNone(features.buy_notional_usd)
        self.assertIsNone(features.notional_imbalance_pct)
        self.assertIn("partial_notional_coverage", features.data_quality_flags)
        self.assertIn("partial_price_coverage", features.data_quality_flags)
        self.assertIn("partial_wallet_identity_coverage", features.data_quality_flags)

    def test_future_quote_is_excluded_from_execution_surface(self):
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
        self.assertIsNone(snapshot.execution.latest_sell_price_usd)
        self.assertIn("sell_quote_unavailable", snapshot.execution.data_quality_flags)
        self.assertIn("proxy_quotes_only", snapshot.execution.data_quality_flags)

    def test_snapshot_has_no_score_or_trading_decision(self):
        snapshot = build_opportunity_snapshot_core_v1(token_mint="T", as_of=1_000)

        self.assertFalse(hasattr(snapshot, "score"))
        self.assertFalse(hasattr(snapshot, "decision"))
        self.assertEqual(snapshot.method_version, "opportunity_snapshot_core_v1")

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
