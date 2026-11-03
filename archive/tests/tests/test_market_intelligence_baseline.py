import unittest

from src.market_intelligence_baseline import (
    MARKET_INTELLIGENCE_BASELINE_VERSION,
    build_market_intelligence_baseline_v0,
)
from src.market_protocol_facts import (
    PumpCurveStateObservation,
    build_market_protocol_facts_v0,
)
from src.matched_unit_flow import (
    MatchedUnitFlowObservation,
    build_matched_unit_flow_facts_v0,
)
from src.opportunity_snapshot_core import (
    FlowTradeObservation,
    build_opportunity_snapshot_core_v1,
)


class MarketIntelligenceBaselineV0Tests(unittest.TestCase):
    def _protocol(self, *, as_of=200, token_mint="MINT_A"):
        return build_market_protocol_facts_v0(
            token_mint=token_mint,
            as_of=as_of,
            pump_curve_observations=(
                PumpCurveStateObservation(
                    token_mint=token_mint,
                    chain_time=100,
                    observed_at=101,
                    evidence_key="curve-100",
                    source="synthetic",
                    complete=False,
                    quote_mint="SOL",
                    virtual_token_reserves=1_000,
                    virtual_quote_reserves=100,
                    real_token_reserves=800,
                    real_quote_reserves=20,
                    token_total_supply=1_000,
                ),
            ),
        )

    def _snapshot(self, *, as_of=200, chain_as_of=None, token_mint="MINT_A"):
        if chain_as_of is None:
            chain_as_of = as_of
        flow = (
            FlowTradeObservation(token_mint, "buy", 190, 191, "W1", 60.0, 1.0),
            FlowTradeObservation(token_mint, "buy", 195, 196, "W2", 30.0, 1.1),
            FlowTradeObservation(token_mint, "sell", 199, 200, "W1", 10.0, 1.2),
        )
        return build_opportunity_snapshot_core_v1(
            token_mint=token_mint,
            as_of=as_of,
            chain_as_of=chain_as_of,
            flow_observations=flow,
            quotes=(),
            flow_windows_seconds=(30, 300),
        )

    def _matched(self, *, as_of=200, chain_as_of=None, token_mint="MINT_A"):
        if chain_as_of is None:
            chain_as_of = as_of
        return build_matched_unit_flow_facts_v0(
            token_mint=token_mint,
            as_of=as_of,
            chain_as_of=chain_as_of,
            windows_seconds=(30, 300),
            observations=(
                MatchedUnitFlowObservation(
                    token_mint=token_mint,
                    side="buy",
                    chain_time=195,
                    observed_at=196,
                    venue="pump",
                    market_surface_key=f"pump:{token_mint}",
                    quote_asset_key="SOL",
                    quote_amount_raw=10,
                    quote_reserve_raw=100,
                    reserve_kind="pump_virtual_quote",
                    evidence_key="matched-195",
                ),
            ),
        )

    def test_composes_protocol_flow_and_execution_without_score(self):
        baseline = build_market_intelligence_baseline_v0(
            protocol=self._protocol(), snapshot=self._snapshot()
        )
        self.assertEqual(baseline.method_version, MARKET_INTELLIGENCE_BASELINE_VERSION)
        self.assertEqual(baseline.chain_as_of, 200)
        self.assertEqual(baseline.lifecycle_label, "PUMP_BONDING_ACTIVE")
        self.assertEqual([item.window_seconds for item in baseline.windows], [30, 300])
        fast = baseline.windows[0]
        self.assertEqual(fast.event_count, 3)
        self.assertAlmostEqual(fast.event_rate_per_second, 0.1)
        self.assertAlmostEqual(fast.buy_event_share_pct, 200.0 / 3.0)
        self.assertAlmostEqual(fast.event_imbalance_pct, 100.0 / 3.0)
        self.assertEqual(fast.unique_buy_wallet_count, 2)
        self.assertEqual(fast.unique_sell_wallet_count, 1)
        self.assertAlmostEqual(fast.notional_imbalance_pct, 80.0)
        self.assertAlmostEqual(fast.return_pct, 20.0)
        self.assertIsNone(fast.median_observation_lag_seconds)
        self.assertEqual(baseline.execution.quote_count, 0)
        forbidden = {"score", "confidence", "recommendation", "take", "skip", "social"}
        self.assertTrue(forbidden.isdisjoint(baseline.__dataclass_fields__))

    def test_dimensional_gap_is_explicit_not_fabricated(self):
        baseline = build_market_intelligence_baseline_v0(
            protocol=self._protocol(), snapshot=self._snapshot()
        )
        self.assertFalse(baseline.liquidity_normalized_flow_available)
        self.assertIsNone(baseline.matched_unit_flow)
        self.assertIn(
            "matched_unit_liquidity_normalized_flow_unavailable",
            baseline.data_quality_flags,
        )
        self.assertFalse(hasattr(baseline.windows[0], "liquidity_normalized_flow"))

    def test_valid_same_unit_facts_enable_liquidity_normalized_flow(self):
        matched = self._matched()
        baseline = build_market_intelligence_baseline_v0(
            protocol=self._protocol(), snapshot=self._snapshot(), matched_unit_flow=matched
        )
        self.assertTrue(baseline.liquidity_normalized_flow_available)
        self.assertIs(baseline.matched_unit_flow, matched)
        self.assertNotIn(
            "matched_unit_liquidity_normalized_flow_unavailable",
            baseline.data_quality_flags,
        )
        fast = next(item for item in matched.surface_windows if item.window_seconds == 30)
        self.assertAlmostEqual(fast.cumulative_signed_event_reserve_fraction_pct, 10.0)
        self.assertEqual(baseline.provenance_keys, ("curve-100", "matched-195"))

    def test_refuses_matched_unit_cross_token_join(self):
        with self.assertRaisesRegex(ValueError, "matched_unit_flow token_mint"):
            build_market_intelligence_baseline_v0(
                protocol=self._protocol(),
                snapshot=self._snapshot(),
                matched_unit_flow=self._matched(token_mint="MINT_B"),
            )

    def test_refuses_matched_unit_cross_local_clock_join(self):
        with self.assertRaisesRegex(ValueError, "matched_unit_flow as_of"):
            build_market_intelligence_baseline_v0(
                protocol=self._protocol(),
                snapshot=self._snapshot(),
                matched_unit_flow=self._matched(as_of=201, chain_as_of=200),
            )

    def test_refuses_matched_unit_cross_chain_anchor_join(self):
        with self.assertRaisesRegex(ValueError, "matched_unit_flow chain_as_of"):
            build_market_intelligence_baseline_v0(
                protocol=self._protocol(),
                snapshot=self._snapshot(chain_as_of=200),
                matched_unit_flow=self._matched(chain_as_of=201),
            )

    def test_protocol_provenance_is_retained(self):
        baseline = build_market_intelligence_baseline_v0(
            protocol=self._protocol(), snapshot=self._snapshot()
        )
        self.assertEqual(baseline.provenance_keys, ("curve-100",))

    def test_missing_wallet_identity_stays_missing(self):
        flow = (
            FlowTradeObservation(
                token_mint="MINT_A",
                side="buy",
                chain_time=199,
                observed_at=200,
                wallet_address=None,
                notional_usd=10.0,
                price_usd=1.0,
            ),
        )
        snapshot = build_opportunity_snapshot_core_v1(
            token_mint="MINT_A",
            as_of=200,
            chain_as_of=200,
            flow_observations=flow,
            quotes=(),
            flow_windows_seconds=(30,),
        )
        baseline = build_market_intelligence_baseline_v0(
            protocol=self._protocol(), snapshot=snapshot
        )
        fast = baseline.windows[0]
        self.assertEqual(fast.wallet_identity_coverage_pct, 0.0)
        self.assertIsNone(fast.repeated_wallet_event_share_pct)
        self.assertIn("partial_wallet_identity_coverage", fast.data_quality_flags)
        self.assertIn("partial_wallet_identity_coverage", baseline.data_quality_flags)

    def test_empty_flow_is_descriptive_and_not_a_signal(self):
        snapshot = build_opportunity_snapshot_core_v1(
            token_mint="MINT_A",
            as_of=200,
            flow_observations=(),
            quotes=(),
            flow_windows_seconds=(30,),
        )
        baseline = build_market_intelligence_baseline_v0(
            protocol=self._protocol(), snapshot=snapshot
        )
        self.assertEqual(baseline.windows[0].event_count, 0)
        self.assertIsNone(baseline.windows[0].buy_event_share_pct)
        self.assertIsNone(baseline.windows[0].event_imbalance_pct)
        self.assertIn("no_flow_context", baseline.data_quality_flags)

    def test_refuses_cross_token_join(self):
        with self.assertRaises(ValueError):
            build_market_intelligence_baseline_v0(
                protocol=self._protocol(token_mint="MINT_A"),
                snapshot=self._snapshot(token_mint="MINT_B"),
            )

    def test_refuses_cross_clock_join(self):
        with self.assertRaises(ValueError):
            build_market_intelligence_baseline_v0(
                protocol=self._protocol(as_of=200), snapshot=self._snapshot(as_of=201)
            )


if __name__ == "__main__":
    unittest.main()
