import unittest

from src.carbon_market_trade_adapter import (
    adapt_carbon_matched_unit_to_market_trade_v0,
)
from src.carbon_matched_unit_adapter import (
    ADAPTED,
    MISSING_CONTEXT,
    CARBON_MATCHED_UNIT_ADAPTER_VERSION,
    CarbonMatchedUnitAdaptationResultV0,
)
from src.matched_unit_flow import MatchedUnitFlowObservation


def _matched(*, event_key: str, token: str, venue: str, side: str = "buy"):
    observation = MatchedUnitFlowObservation(
        token_mint=token,
        side=side,
        chain_time=100,
        observed_at=200,
        venue=venue,
        market_surface_key=f"{venue}:surface",
        quote_asset_key="QUOTE",
        quote_amount_raw=10,
        quote_reserve_raw=1000,
        reserve_kind="test",
        evidence_key=event_key,
    )
    return CarbonMatchedUnitAdaptationResultV0(
        method_version=CARBON_MATCHED_UNIT_ADAPTER_VERSION,
        event_key=event_key,
        status=ADAPTED,
        observation=observation,
        provenance_keys=(event_key,),
        data_quality_flags=(),
    )


class CarbonMarketTradeAdapterTests(unittest.TestCase):
    def test_pump_trade_maps_identity_wallet_and_transaction_without_usd_inference(self):
        row = {
            "type": "carbon_canonical_event",
            "status": "decoded",
            "event_key": "E1",
            "event_type": "pump_trade",
            "mint": "TOKEN",
            "side": "buy",
            "timestamp": 100,
            "wallet": "WALLET",
            "signature": "SIG",
        }
        result = adapt_carbon_matched_unit_to_market_trade_v0(
            row, _matched(event_key="E1", token="TOKEN", venue="pump")
        )
        self.assertEqual(result.status, ADAPTED)
        self.assertIsNotNone(result.observation)
        assert result.observation is not None
        self.assertEqual(result.observation.token_mint, "TOKEN")
        self.assertEqual(result.observation.wallet_address, "WALLET")
        self.assertEqual(result.observation.transaction_key, "SIG")
        self.assertEqual(result.observation.observed_at, 200)
        self.assertIsNone(result.observation.notional_usd)
        self.assertIsNone(result.observation.price_usd)
        self.assertIn("usd_notional_not_inferred", result.data_quality_flags)
        self.assertIn("usd_price_not_inferred", result.data_quality_flags)

    def test_pumpswap_trade_uses_causally_resolved_token_identity(self):
        row = {
            "type": "carbon_canonical_event",
            "status": "decoded",
            "event_key": "E2",
            "event_type": "pumpswap_buy",
            "pool": "POOL",
            "side": "buy",
            "timestamp": 100,
            "user": "USER",
            "signature": "SIG2",
        }
        result = adapt_carbon_matched_unit_to_market_trade_v0(
            row, _matched(event_key="E2", token="RESOLVED_TOKEN", venue="pumpswap")
        )
        self.assertEqual(result.status, ADAPTED)
        assert result.observation is not None
        self.assertEqual(result.observation.token_mint, "RESOLVED_TOKEN")
        self.assertEqual(result.observation.wallet_address, "USER")
        self.assertEqual(result.observation.venue, "pumpswap")

    def test_missing_pumpswap_context_remains_missing(self):
        row = {
            "type": "carbon_canonical_event",
            "status": "decoded",
            "event_key": "E3",
            "event_type": "pumpswap_sell",
            "side": "sell",
            "timestamp": 100,
            "user": "USER",
            "signature": "SIG3",
        }
        matched = CarbonMatchedUnitAdaptationResultV0(
            method_version=CARBON_MATCHED_UNIT_ADAPTER_VERSION,
            event_key="E3",
            status=MISSING_CONTEXT,
            observation=None,
            provenance_keys=(),
            data_quality_flags=("pool_identity_missing",),
        )
        result = adapt_carbon_matched_unit_to_market_trade_v0(row, matched)
        self.assertEqual(result.status, MISSING_CONTEXT)
        self.assertIsNone(result.observation)
        self.assertIn("matched_unit_observation_unavailable", result.data_quality_flags)

    def test_event_key_mismatch_fails_closed(self):
        row = {
            "type": "carbon_canonical_event",
            "status": "decoded",
            "event_key": "ROW",
            "event_type": "pump_trade",
            "mint": "TOKEN",
            "side": "buy",
            "timestamp": 100,
        }
        result = adapt_carbon_matched_unit_to_market_trade_v0(
            row, _matched(event_key="MATCHED", token="TOKEN", venue="pump")
        )
        self.assertEqual(result.status, "INVALID_EVENT")
        self.assertIsNone(result.observation)
        self.assertIn("carbon_matched_unit_event_key_mismatch", result.data_quality_flags)


if __name__ == "__main__":
    unittest.main()
