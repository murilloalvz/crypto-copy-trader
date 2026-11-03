import dataclasses
import unittest

from src.market_activity_dynamics_v0 import (
    MARKET_ACTIVITY_DYNAMICS_VERSION,
    build_market_activity_dynamics_v0,
)
from src.opportunity_snapshot_core import (
    FlowTradeObservation,
    build_opportunity_snapshot_core_v1,
)


class MarketActivityDynamicsV0Tests(unittest.TestCase):
    def _snapshot(self, *, partial_notional=False):
        rows = (
            FlowTradeObservation(
                token_mint="MINT_A",
                side="buy",
                chain_time=995,
                observed_at=100,
                wallet_address="A",
                notional_usd=10.0,
                price_usd=1.00,
            ),
            FlowTradeObservation(
                token_mint="MINT_A",
                side="buy",
                chain_time=993,
                observed_at=101,
                wallet_address="B",
                notional_usd=20.0,
                price_usd=1.01,
            ),
            FlowTradeObservation(
                token_mint="MINT_A",
                side="sell",
                chain_time=980,
                observed_at=102,
                wallet_address="A",
                notional_usd=None if partial_notional else 5.0,
                price_usd=1.02,
            ),
            FlowTradeObservation(
                token_mint="MINT_A",
                side="buy",
                chain_time=950,
                observed_at=103,
                wallet_address="C",
                notional_usd=30.0,
                price_usd=1.03,
            ),
            FlowTradeObservation(
                token_mint="MINT_A",
                side="sell",
                chain_time=800,
                observed_at=104,
                wallet_address="D",
                notional_usd=15.0,
                price_usd=1.04,
            ),
        )
        return build_opportunity_snapshot_core_v1(
            token_mint="MINT_A",
            as_of=110,
            chain_as_of=1000,
            flow_observations=rows,
            quotes=(),
            flow_windows_seconds=(10, 30, 60, 300),
        )

    def test_derives_non_overlapping_observed_activity_without_thresholds(self):
        result = build_market_activity_dynamics_v0(self._snapshot())

        self.assertEqual(result.method_version, MARKET_ACTIVITY_DYNAMICS_VERSION)
        self.assertEqual(result.token_mint, "MINT_A")
        self.assertEqual(result.as_of, 110)
        self.assertEqual(result.chain_as_of, 1000)

        self.assertEqual(
            [item.observed_event_count for item in result.intervals],
            [2, 1, 1, 1],
        )
        self.assertEqual(
            [item.observed_buy_count for item in result.intervals],
            [2, 0, 1, 0],
        )
        self.assertEqual(
            [item.observed_sell_count for item in result.intervals],
            [0, 1, 0, 1],
        )
        self.assertEqual(
            [item.observed_total_notional_usd for item in result.intervals],
            [30.0, 5.0, 30.0, 15.0],
        )
        self.assertEqual(
            [item.observed_signed_notional_usd for item in result.intervals],
            [30.0, -5.0, 30.0, -15.0],
        )

        comparisons = result.adjacent_rate_comparisons
        self.assertAlmostEqual(comparisons[0].observed_event_rate_ratio, 4.0)
        self.assertAlmostEqual(comparisons[1].observed_event_rate_ratio, 1.5)
        self.assertAlmostEqual(comparisons[2].observed_event_rate_ratio, 8.0)
        self.assertAlmostEqual(comparisons[0].observed_total_notional_rate_ratio, 12.0)
        self.assertIsNone(comparisons[0].observed_buy_rate_ratio)
        self.assertEqual(comparisons[0].observed_sell_rate_ratio, 0.0)

    def test_participant_context_stays_cumulative_and_is_not_subtracted(self):
        result = build_market_activity_dynamics_v0(self._snapshot())
        context = result.participant_context

        self.assertEqual([item.cumulative_window_seconds for item in context], [10, 30, 60])
        self.assertEqual([item.unique_buy_wallet_count for item in context], [2, 2, 3])
        self.assertEqual([item.unique_sell_wallet_count for item in context], [0, 1, 1])
        self.assertAlmostEqual(context[1].repeated_wallet_event_share_pct, 100.0 / 3.0)

        interval_fields = {field.name for field in dataclasses.fields(result.intervals[0])}
        self.assertNotIn("unique_buy_wallet_count", interval_fields)
        self.assertNotIn("unique_sell_wallet_count", interval_fields)

    def test_partial_notional_coverage_remains_missing(self):
        result = build_market_activity_dynamics_v0(self._snapshot(partial_notional=True))
        interval_10_30 = result.intervals[1]

        self.assertEqual(interval_10_30.observed_event_count, 1)
        self.assertIsNone(interval_10_30.observed_total_notional_usd)
        self.assertIsNone(interval_10_30.observed_signed_notional_usd)
        self.assertIsNone(interval_10_30.observed_total_notional_rate_usd_per_second)
        self.assertIn(
            "interval_notional_unavailable_from_cumulative_coverage",
            interval_10_30.data_quality_flags,
        )
        self.assertIsNone(
            result.adjacent_rate_comparisons[0].observed_total_notional_rate_ratio
        )

    def test_missing_required_cumulative_window_fails_closed(self):
        snapshot = build_opportunity_snapshot_core_v1(
            token_mint="MINT_A",
            as_of=110,
            chain_as_of=None,
            flow_observations=(),
            quotes=(),
            flow_windows_seconds=(10, 30, 60),
        )
        with self.assertRaisesRegex(ValueError, "missing required cumulative flow windows"):
            build_market_activity_dynamics_v0(snapshot)

    def test_no_observed_activity_is_not_promoted_to_true_zero_claim(self):
        snapshot = build_opportunity_snapshot_core_v1(
            token_mint="MINT_A",
            as_of=110,
            chain_as_of=None,
            flow_observations=(),
            quotes=(),
            flow_windows_seconds=(10, 30, 60, 300),
        )
        result = build_market_activity_dynamics_v0(snapshot)

        self.assertEqual(sum(item.observed_event_count for item in result.intervals), 0)
        self.assertIn(
            "observed_activity_only_no_chain_completeness_claim",
            result.data_quality_flags,
        )
        self.assertIn(
            "no_observed_activity_not_proven_true_zero",
            result.data_quality_flags,
        )
        self.assertTrue(
            all(
                item.observed_event_rate_ratio is None
                for item in result.adjacent_rate_comparisons
            )
        )

    def test_output_has_no_outcome_score_confidence_or_recommendation_fields(self):
        result = build_market_activity_dynamics_v0(self._snapshot())
        payload = dataclasses.asdict(result)
        forbidden = {
            "outcome",
            "score",
            "confidence",
            "recommendation",
            "take",
            "skip",
            "pnl",
            "return",
        }

        def walk(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    lowered = str(key).lower()
                    for word in forbidden:
                        self.assertNotIn(word, lowered)
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(payload)


if __name__ == "__main__":
    unittest.main()
