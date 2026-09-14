import unittest

from src.market_protocol_facts import (
    PumpCurveStateObservation,
    build_market_protocol_facts_v0,
)
from src.pump_direct_buy_quote_state_adapter_v0 import (
    STATE_CURVE_COMPLETE,
    STATE_MISSING,
    STATE_READY,
    adapt_pump_protocol_facts_to_buy_quote_state_v0,
)


class PumpDirectBuyQuoteStateAdapterV0Tests(unittest.TestCase):
    def _observation(self, *, observed_at=90, complete=False):
        return PumpCurveStateObservation(
            token_mint="MINT",
            chain_time=80,
            observed_at=observed_at,
            evidence_key=f"curve:{observed_at}",
            source="carbon",
            complete=complete,
            quote_mint="SOL",
            virtual_token_reserves=1_000_000,
            virtual_quote_reserves=500_000,
            real_token_reserves=700_000 if not complete else 0,
            real_quote_reserves=100_000,
            token_total_supply=1_000_000,
        )

    def test_ready_state_reuses_existing_causal_protocol_facts(self):
        facts = build_market_protocol_facts_v0(
            token_mint="MINT",
            as_of=100,
            pump_curve_observations=(self._observation(),),
        )
        adapted = adapt_pump_protocol_facts_to_buy_quote_state_v0(facts)
        self.assertEqual(adapted.status, STATE_READY)
        self.assertEqual(adapted.as_of, 100)
        self.assertEqual(adapted.quote_mint, "SOL")
        self.assertEqual(adapted.state.virtual_token_reserves_raw, 1_000_000)
        self.assertEqual(adapted.state.virtual_quote_reserves_raw, 500_000)
        self.assertEqual(adapted.state.real_token_reserves_raw, 700_000)
        self.assertEqual(adapted.provenance_keys, ("curve:90",))

    def test_future_arriving_curve_state_is_not_backfilled(self):
        facts = build_market_protocol_facts_v0(
            token_mint="MINT",
            as_of=100,
            pump_curve_observations=(self._observation(observed_at=110),),
        )
        adapted = adapt_pump_protocol_facts_to_buy_quote_state_v0(facts)
        self.assertEqual(adapted.status, STATE_MISSING)
        self.assertIsNone(adapted.state)
        self.assertIn("direct_pump_quote_state_incomplete", adapted.data_quality_flags)

    def test_completed_curve_is_not_exposed_as_active_quote_state(self):
        facts = build_market_protocol_facts_v0(
            token_mint="MINT",
            as_of=100,
            pump_curve_observations=(self._observation(complete=True),),
        )
        adapted = adapt_pump_protocol_facts_to_buy_quote_state_v0(facts)
        self.assertEqual(adapted.status, STATE_CURVE_COMPLETE)
        self.assertIsNone(adapted.state)

    def test_partial_reserve_observation_is_missing_not_zero_filled(self):
        row = PumpCurveStateObservation(
            token_mint="MINT",
            chain_time=80,
            observed_at=90,
            evidence_key="partial",
            source="carbon",
            complete=False,
            quote_mint="SOL",
            virtual_token_reserves=1_000_000,
            virtual_quote_reserves=None,
            real_token_reserves=700_000,
        )
        facts = build_market_protocol_facts_v0(
            token_mint="MINT", as_of=100, pump_curve_observations=(row,)
        )
        adapted = adapt_pump_protocol_facts_to_buy_quote_state_v0(facts)
        self.assertEqual(adapted.status, STATE_MISSING)
        self.assertIn("pump_virtual_quote_reserves", adapted.missing_fields)
        self.assertIsNone(adapted.state)


if __name__ == "__main__":
    unittest.main()
