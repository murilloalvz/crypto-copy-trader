import unittest

from src.carbon_market_trade_adapter import adapt_carbon_matched_unit_to_market_trade_v0
from src.carbon_matched_unit_adapter import ADAPTED, CarbonMatchedUnitAdaptationResultV0
from src.launch_burst_source_capabilities_v0 import (
    build_launch_burst_source_capabilities_v0,
)
from src.matched_unit_flow import MATCHED_UNIT_FLOW_VERSION, MatchedUnitFlowObservation


class LaunchBurstSourceCapabilitiesV0Tests(unittest.TestCase):
    def test_feature_only_ready_but_economic_outcomes_fail_closed(self):
        report = build_launch_burst_source_capabilities_v0()
        self.assertTrue(report.feature_only_ready)
        self.assertFalse(report.economic_outcome_ready)
        self.assertTrue(report.executable_quote_selection_contract_present)
        self.assertFalse(report.executable_quote_collector_proven)
        self.assertIn(
            "official_executable_launch_burst_outcome_collector_not_proven",
            report.blockers,
        )

    def test_current_market_adapter_does_not_manufacture_usd_price_or_notional(self):
        event_key = "pump:sig:0"
        row = {
            "type": "carbon_canonical_event",
            "status": "decoded",
            "event_type": "pump_trade",
            "event_key": event_key,
            "mint": "TOKEN",
            "side": "buy",
            "timestamp": 1000,
            "wallet": "WALLET",
            "signature": "SIG",
        }
        matched = CarbonMatchedUnitAdaptationResultV0(
            method_version="test",
            event_key=event_key,
            status=ADAPTED,
            observation=MatchedUnitFlowObservation(
                token_mint="TOKEN",
                side="buy",
                chain_time=1000,
                observed_at=2000,
                venue="pump",
                market_surface_key="pump:TOKEN",
                quote_asset_key="SOL",
                quote_amount_raw=123,
                quote_reserve_raw=4567,
                reserve_kind="pump_virtual_quote_event",
                evidence_key=event_key,
            ),
            provenance_keys=(event_key,),
            data_quality_flags=(),
        )
        adapted = adapt_carbon_matched_unit_to_market_trade_v0(row, matched)
        self.assertEqual(adapted.status, ADAPTED)
        self.assertIsNotNone(adapted.observation)
        assert adapted.observation is not None
        self.assertIsNone(adapted.observation.notional_usd)
        self.assertIsNone(adapted.observation.price_usd)
        self.assertEqual(adapted.observation.venue, "pump")
        self.assertIn("usd_notional_not_inferred", adapted.data_quality_flags)
        self.assertIn("usd_price_not_inferred", adapted.data_quality_flags)

    def test_matched_unit_capability_is_known_but_not_claimed_as_sqlite_durable(self):
        report = build_launch_burst_source_capabilities_v0()
        self.assertEqual(report.matched_unit_flow_version, MATCHED_UNIT_FLOW_VERSION)
        by_family = {item.field_family: item for item in report.capabilities}
        native = by_family["native_quote_amount_and_reserve"]
        dimensionless = by_family["dimensionless_flow_over_reserve"]
        self.assertEqual(native.current_status, "AVAILABLE_IN_MEMORY_AND_RAW_REPLAY")
        self.assertFalse(native.durable_in_market_observation_store)
        self.assertFalse(native.usable_for_launch_burst_v0)
        self.assertEqual(
            dimensionless.current_status,
            "COMPUTABLE_FROM_MATCHED_UNIT_EVIDENCE",
        )
        self.assertFalse(dimensionless.durable_in_market_observation_store)


if __name__ == "__main__":
    unittest.main()
