import unittest

from src.multichain_launch_burst_contract_v0 import (
    RAW_QUOTE_UNIT,
    adapt_robinhood_pons_snapshot_v0,
    adapt_solana_pump_snapshot_v0,
    assert_normalized_comparable_v0,
    assert_raw_quote_comparable_v0,
    normalize_feature_v0,
)


class MultichainLaunchBurstContractV0Tests(unittest.TestCase):
    def solana_snapshot(self):
        return {
            "stratum": "pump_launch",
            "complete": True,
            "observed_t0": 100,
            "observed_t0_wall_ns": 100_000_000_000,
            "evidence_window_seconds": 5,
            "decision_as_of": 105,
            "decision_cutoff_wall_ns": 105_000_000_000,
            "features": {
                "event_count": 7,
                "buy_count": 5,
                "sell_count": 2,
                "buy_sell_count_imbalance": 3 / 7,
                "signed_flow_over_event_reserve": 0.12,
                "gross_turnover_over_event_reserve": 0.2,
                "signed_quote_amount_raw": 2_000_000,
                "gross_quote_amount_raw": 3_000_000,
                "raw_quote_amount_aggregation_valid": True,
                "quote_asset_identity_count": 1,
                "market_surface_count": 1,
                "unique_wallet_count": 0,
                "wallet_identity_coverage_pct": 0.0,
                "unique_transaction_count": 7,
                "transaction_identity_coverage_pct": 100.0,
                "first_trade_delay_ms": 130.0,
                "time_to_n_events_ms": {"1": 130.0, "3": 500.0, "5": 900.0, "10": None},
                "reserve_delta_fraction": 0.1,
            },
        }

    def robinhood_snapshot(self, pair_token="0x0000000000000000000000000000000000000000"):
        return {
            "method_version": "robinhood_pons_launch_burst_v0",
            "token": "0x1111111111111111111111111111111111111111",
            "curve": "0x2222222222222222222222222222222222222222",
            "deployer": "0x3333333333333333333333333333333333333333",
            "pair_token": pair_token,
            "native_eth_cohort": pair_token == "0x0000000000000000000000000000000000000000",
            "graduation_threshold_raw": 4_200_000_000_000_000_000,
            "horizon_seconds": 5,
            "launch_observed_at_ns": 200_000_000_000,
            "cutoff_observed_at_ns": 205_000_000_000,
            "snapshot_observed_at_ns": 205_100_000_000,
            "snapshot_dispatch_lag_ms": 100.0,
            "trade_count": 6,
            "buy_count": 5,
            "sell_count": 1,
            "unique_actors": 5,
            "unique_buyers": 4,
            "unique_sellers": 1,
            "unique_recipients": 5,
            "recipient_mismatch_count": 0,
            "recipient_mismatch_share": 0.0,
            "gross_buy_quote_raw": 2_000_000_000_000_000,
            "gross_sell_quote_raw": 300_000_000_000_000,
            "gross_quote_activity_raw": 2_300_000_000_000_000,
            "signed_quote_flow_raw": 1_700_000_000_000_000,
            "signed_quote_flow_over_activity": 1.7 / 2.3,
            "gross_tokens_bought_raw": 100_000,
            "gross_tokens_sold_raw": 10_000,
            "net_token_demand_raw": 90_000,
            "fee_raw": 50_000_000_000_000,
            "tax_raw": 5_000_000_000_000,
            "buy_fee_share_bps_observed": 250.0,
            "buy_total_charge_share_bps_observed": 275.0,
            "sell_total_charge_share_bps_observed": 300.0,
            "deployer_buy_quote_raw": 100_000_000_000_000,
            "deployer_buy_quote_share": 0.05,
            "top1_buyer_quote_share": 0.35,
            "top3_buyer_quote_share": 0.8,
            "first_trade_delay_ms": 90.0,
            "time_to_3_trades_ms": 400.0,
            "time_to_5_trades_ms": 900.0,
            "median_interarrival_ms": 180.0,
            "max_interarrival_ms": 300.0,
            "trade_rate_per_second": 1.2,
            "early_half_trade_count": 4,
            "late_half_trade_count": 2,
            "half_window_acceleration": -0.5,
            "first_buy_effective_quote_per_token": 10.0,
            "last_buy_effective_quote_per_token": 12.0,
            "buy_effective_price_ratio_last_over_first": 1.2,
            "first_chain_order": [100, 0, 1],
            "last_chain_order": [105, 0, 2],
            "data_quality_flags": [],
        }

    def test_solana_adapter_is_lossless_and_namespaced(self):
        source = self.solana_snapshot()
        envelope = adapt_solana_pump_snapshot_v0(
            token_mint="Mint111",
            snapshot=source,
            snapshot_observed_at_ns=105_050_000_000,
            provenance=("solana-feature-artifact:sha256:test",),
            selector_frozen=True,
        )
        self.assertEqual(envelope.source_snapshot(), source)
        self.assertEqual(envelope.feature_namespace, "solana.pump.launch_burst_shadow_v0")
        self.assertEqual(envelope.features, source["features"])
        self.assertTrue(envelope.selector_frozen)
        self.assertTrue(envelope.feature_only)
        self.assertFalse(envelope.economic_outcomes_opened)
        self.assertIsNone(envelope.quote_unit.asset_id)
        self.assertIsNone(envelope.quote_unit.decimals)
        self.assertIn("quote_asset_identity_missing", envelope.data_quality_flags)

    def test_robinhood_adapter_is_lossless_and_namespaced(self):
        source = self.robinhood_snapshot()
        envelope = adapt_robinhood_pons_snapshot_v0(
            snapshot=source,
            provenance=("robinhood-capture:run-test",),
        )
        self.assertEqual(envelope.source_snapshot(), source)
        self.assertEqual(envelope.feature_namespace, "robinhood.pons_v2.launch_burst_v0")
        self.assertEqual(envelope.quote_unit.unit_kind, RAW_QUOTE_UNIT)
        self.assertEqual(envelope.quote_unit.semantic_asset_id, "ETH")
        self.assertEqual(envelope.quote_unit.decimals, 18)
        self.assertEqual(envelope.features["signed_quote_flow_raw"], source["signed_quote_flow_raw"])
        self.assertNotIn("signed_flow_over_event_reserve", envelope.features)

    def test_custom_pair_stays_nonheadline_and_missing_metadata_stays_missing(self):
        source = self.robinhood_snapshot("0x4444444444444444444444444444444444444444")
        envelope = adapt_robinhood_pons_snapshot_v0(snapshot=source)
        self.assertIsNone(envelope.quote_unit.semantic_asset_id)
        self.assertIsNone(envelope.quote_unit.decimals)
        self.assertIn("custom_pair_nonheadline", envelope.data_quality_flags)
        self.assertIn("quote_semantic_identity_missing", envelope.data_quality_flags)

    def test_raw_solana_vs_robinhood_quote_comparison_refuses_incompatible_assets(self):
        solana = adapt_solana_pump_snapshot_v0(
            token_mint="Mint111",
            snapshot=self.solana_snapshot(),
            snapshot_observed_at_ns=105_010_000_000,
            quote_asset_id="So111",
            quote_asset_decimals=9,
            quote_semantic_asset_id="SOL",
        )
        robinhood = adapt_robinhood_pons_snapshot_v0(snapshot=self.robinhood_snapshot())
        with self.assertRaisesRegex(ValueError, "semantically different"):
            assert_raw_quote_comparable_v0(solana, robinhood)

    def test_raw_comparison_refuses_missing_quote_metadata(self):
        solana = adapt_solana_pump_snapshot_v0(
            token_mint="Mint111",
            snapshot=self.solana_snapshot(),
            snapshot_observed_at_ns=105_010_000_000,
        )
        robinhood = adapt_robinhood_pons_snapshot_v0(snapshot=self.robinhood_snapshot())
        with self.assertRaisesRegex(ValueError, "requires explicit"):
            assert_raw_quote_comparable_v0(solana, robinhood)

    def test_explicit_causal_normalization_can_create_common_comparison_unit(self):
        solana = adapt_solana_pump_snapshot_v0(
            token_mint="Mint111",
            snapshot=self.solana_snapshot(),
            snapshot_observed_at_ns=105_010_000_000,
            quote_asset_id="So111",
            quote_asset_decimals=9,
            quote_semantic_asset_id="SOL",
        )
        robinhood = adapt_robinhood_pons_snapshot_v0(snapshot=self.robinhood_snapshot())
        left = normalize_feature_v0(
            solana,
            source_feature_name="signed_quote_amount_raw",
            semantic_feature_name="signed_quote_flow_value",
            factor=150.0 / 1_000_000_000,
            common_unit="USD",
            normalization_observed_at_ns=104_900_000_000,
            normalization_provenance=("price:SOLUSD:causal-test",),
        )
        right = normalize_feature_v0(
            robinhood,
            source_feature_name="signed_quote_flow_raw",
            semantic_feature_name="signed_quote_flow_value",
            factor=4_000.0 / 1_000_000_000_000_000_000,
            common_unit="USD",
            normalization_observed_at_ns=204_900_000_000,
            normalization_provenance=("price:ETHUSD:causal-test",),
        )
        assert_normalized_comparable_v0(left, right)
        self.assertEqual(left.common_unit, "USD")
        self.assertEqual(right.common_unit, "USD")

    def test_future_normalization_evidence_is_rejected(self):
        solana = adapt_solana_pump_snapshot_v0(
            token_mint="Mint111",
            snapshot=self.solana_snapshot(),
            snapshot_observed_at_ns=105_010_000_000,
        )
        with self.assertRaisesRegex(ValueError, "after the feature cutoff"):
            normalize_feature_v0(
                solana,
                source_feature_name="signed_quote_amount_raw",
                semantic_feature_name="signed_quote_flow_value",
                factor=1.0,
                common_unit="USD",
                normalization_observed_at_ns=106_000_000_000,
                normalization_provenance=("future-price",),
            )

    def test_protocol_features_do_not_gain_fake_cross_chain_aliases(self):
        solana = adapt_solana_pump_snapshot_v0(
            token_mint="Mint111",
            snapshot=self.solana_snapshot(),
            snapshot_observed_at_ns=105_010_000_000,
        )
        robinhood = adapt_robinhood_pons_snapshot_v0(snapshot=self.robinhood_snapshot())
        self.assertIn("signed_flow_over_event_reserve", solana.features)
        self.assertNotIn("signed_quote_flow_over_activity", solana.features)
        self.assertIn("signed_quote_flow_over_activity", robinhood.features)
        self.assertNotIn("signed_flow_over_event_reserve", robinhood.features)

    def test_feature_only_and_outcomes_opened_cannot_both_be_true(self):
        with self.assertRaisesRegex(ValueError, "feature_only"):
            adapt_robinhood_pons_snapshot_v0(
                snapshot=self.robinhood_snapshot(),
                feature_only=True,
                economic_outcomes_opened=True,
            )


if __name__ == "__main__":
    unittest.main()
