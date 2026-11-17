import unittest

from src.carbon_matched_unit_adapter import (
    ADAPTED,
    CONFLICTING_CONTEXT,
    INVALID_EVENT,
    MISSING_CONTEXT,
    UNSUPPORTED_EVENT,
    adapt_carbon_pump_trade_v0,
    adapt_carbon_pumpswap_trade_v0,
)
from src.market_protocol_facts import PumpSwapPoolObservation
from src.pumpswap_pool_identity import PumpSwapPoolIdentityObservation


class CarbonMatchedUnitAdapterV0Tests(unittest.TestCase):
    def _pump(self, **overrides):
        row = dict(
            status="decoded",
            event_type="pump_trade",
            event_key="pump:sig:0",
            mint="MINT_A",
            side="buy",
            timestamp=100,
            quote_mint="SOL_MINT",
            quote_amount_raw=10,
            virtual_quote_reserves_raw=100,
        )
        row.update(overrides)
        return row

    def _swap(self, **overrides):
        row = dict(
            status="decoded",
            event_type="pumpswap_buy",
            event_key="pumpswap:sig:0",
            pool="POOL_A",
            side="buy",
            timestamp=100,
            quote_amount_raw=10,
            pool_quote_token_reserves_raw=200,
        )
        row.update(overrides)
        return row

    def _pool(self, **overrides):
        values = dict(
            token_mint="MINT_A",
            pool="POOL_A",
            chain_time=90,
            observed_at=95,
            evidence_key="pool-state-90",
            source="carbon_pumpswap_pool",
            base_mint="MINT_A",
            quote_mint="USDC_MINT",
            pool_quote_token_reserves=180,
        )
        values.update(overrides)
        return PumpSwapPoolObservation(**values)

    def _identity(self, **overrides):
        values = dict(
            pool="POOL_A",
            base_mint="MINT_A",
            quote_mint="USDC_MINT",
            observed_wall_ns=100_000_000_000,
            observed_slot=120,
            evidence_key="pumpswap_pool_account:POOL_A:120:100000000000",
            source="carbon_pumpswap_pool_account",
        )
        values.update(overrides)
        return PumpSwapPoolIdentityObservation(**values)

    def test_pump_uses_event_native_quote_identity_and_reserve(self):
        result = adapt_carbon_pump_trade_v0(self._pump(), observed_at=101)
        self.assertEqual(result.status, ADAPTED)
        obs = result.observation
        self.assertIsNotNone(obs)
        assert obs is not None
        self.assertEqual(obs.token_mint, "MINT_A")
        self.assertEqual(obs.quote_asset_key, "SOL_MINT")
        self.assertEqual(obs.quote_amount_raw, 10)
        self.assertEqual(obs.quote_reserve_raw, 100)
        self.assertEqual(obs.reserve_kind, "pump_virtual_quote_event")
        self.assertEqual(result.provenance_keys, ("pump:sig:0",))

    def test_pump_invalid_fields_fail_closed(self):
        for row in (
            self._pump(quote_mint=None),
            self._pump(quote_amount_raw=0),
            self._pump(virtual_quote_reserves_raw=0),
        ):
            with self.subTest(row=row):
                result = adapt_carbon_pump_trade_v0(row, observed_at=101)
                self.assertEqual(result.status, INVALID_EVENT)
                self.assertIsNone(result.observation)

    def test_chain_clock_ahead_of_local_clock_is_valid_and_flagged(self):
        result = adapt_carbon_pump_trade_v0(self._pump(timestamp=100), observed_at=99)
        self.assertEqual(result.status, ADAPTED)
        self.assertIsNotNone(result.observation)
        self.assertIn(
            "chain_clock_ahead_of_local_observation_clock", result.data_quality_flags
        )

    def test_non_trade_row_is_unsupported_not_guessed(self):
        result = adapt_carbon_pump_trade_v0(
            self._pump(event_type="pump_create"), observed_at=101
        )
        self.assertEqual(result.status, UNSUPPORTED_EVENT)
        self.assertIsNone(result.observation)

    def test_pumpswap_requires_causal_pool_context(self):
        result = adapt_carbon_pumpswap_trade_v0(
            self._swap(), observed_at=101, pool_observations=()
        )
        self.assertEqual(result.status, MISSING_CONTEXT)
        self.assertIsNone(result.observation)
        self.assertIn(
            "pumpswap_pool_quote_context_missing_at_t0", result.data_quality_flags
        )

    def test_future_pool_context_is_not_backfilled(self):
        result = adapt_carbon_pumpswap_trade_v0(
            self._swap(),
            observed_at=101,
            pool_observations=(self._pool(observed_at=102),),
        )
        self.assertEqual(result.status, MISSING_CONTEXT)

    def test_pool_state_after_trade_chain_time_is_not_used(self):
        result = adapt_carbon_pumpswap_trade_v0(
            self._swap(),
            observed_at=110,
            pool_observations=(self._pool(chain_time=101, observed_at=102),),
        )
        self.assertEqual(result.status, MISSING_CONTEXT)

    def test_pumpswap_uses_exact_pool_quote_mint_without_assuming_sol(self):
        result = adapt_carbon_pumpswap_trade_v0(
            self._swap(),
            observed_at=101,
            pool_observations=(self._pool(quote_mint="USDC_MINT"),),
        )
        self.assertEqual(result.status, ADAPTED)
        obs = result.observation
        self.assertIsNotNone(obs)
        assert obs is not None
        self.assertEqual(obs.token_mint, "MINT_A")
        self.assertEqual(obs.quote_asset_key, "USDC_MINT")
        self.assertEqual(obs.market_surface_key, "pumpswap:POOL_A")
        self.assertEqual(obs.quote_amount_raw, 10)
        self.assertEqual(obs.quote_reserve_raw, 200)
        self.assertEqual(
            result.provenance_keys, ("pumpswap:sig:0", "pool-state-90")
        )

    def test_pumpswap_chain_clock_ahead_is_valid_but_context_still_causal(self):
        identity = self._identity(observed_wall_ns=100_000_000_000)
        result = adapt_carbon_pumpswap_trade_v0(
            self._swap(timestamp=102),
            observed_at=101,
            observed_wall_ns=101_000_000_000,
            pool_observations=(),
            pool_identity_observations=(identity,),
        )
        self.assertEqual(result.status, ADAPTED)
        self.assertIn(
            "chain_clock_ahead_of_local_observation_clock", result.data_quality_flags
        )

    def test_latest_causal_pool_context_wins(self):
        old = self._pool(
            chain_time=80,
            observed_at=81,
            evidence_key="old",
            quote_mint="OLD_QUOTE",
        )
        new = self._pool(
            chain_time=95,
            observed_at=96,
            evidence_key="new",
            quote_mint="NEW_QUOTE",
        )
        result = adapt_carbon_pumpswap_trade_v0(
            self._swap(), observed_at=101, pool_observations=(new, old)
        )
        self.assertEqual(result.status, ADAPTED)
        assert result.observation is not None
        self.assertEqual(result.observation.quote_asset_key, "NEW_QUOTE")
        self.assertEqual(result.provenance_keys[-1], "new")

    def test_same_clock_conflicting_pool_identity_fails_closed(self):
        a = self._pool(evidence_key="a", token_mint="MINT_A", quote_mint="USDC")
        b = self._pool(evidence_key="b", token_mint="MINT_B", quote_mint="SOL")
        result = adapt_carbon_pumpswap_trade_v0(
            self._swap(), observed_at=101, pool_observations=(a, b)
        )
        self.assertEqual(result.status, CONFLICTING_CONTEXT)
        self.assertIsNone(result.observation)
        self.assertIn(
            "pumpswap_pool_quote_context_conflict", result.data_quality_flags
        )

    def test_wrong_pool_context_is_ignored(self):
        result = adapt_carbon_pumpswap_trade_v0(
            self._swap(),
            observed_at=101,
            pool_observations=(self._pool(pool="POOL_B"),),
        )
        self.assertEqual(result.status, MISSING_CONTEXT)

    def test_pre_event_account_identity_enables_pumpswap_without_chain_time_fabrication(self):
        identity = self._identity(observed_wall_ns=100_500_000_000)
        result = adapt_carbon_pumpswap_trade_v0(
            self._swap(),
            observed_at=101,
            observed_wall_ns=101_000_000_000,
            pool_observations=(),
            pool_identity_observations=(identity,),
        )
        self.assertEqual(result.status, ADAPTED)
        assert result.observation is not None
        self.assertEqual(result.observation.token_mint, "MINT_A")
        self.assertEqual(result.observation.quote_asset_key, "USDC_MINT")
        self.assertEqual(result.provenance_keys[-1], identity.evidence_key)

    def test_post_event_account_identity_is_not_backfilled_even_within_same_second(self):
        identity = self._identity(observed_wall_ns=101_900_000_000)
        result = adapt_carbon_pumpswap_trade_v0(
            self._swap(),
            observed_at=101,
            observed_wall_ns=101_100_000_000,
            pool_observations=(),
            pool_identity_observations=(identity,),
        )
        self.assertEqual(result.status, MISSING_CONTEXT)
        self.assertIsNone(result.observation)

    def test_conflicting_account_identity_fails_closed(self):
        a = self._identity(
            observed_wall_ns=99_000_000_000,
            evidence_key="id:a",
            base_mint="MINT_A",
            quote_mint="USDC",
        )
        b = self._identity(
            observed_wall_ns=100_000_000_000,
            evidence_key="id:b",
            base_mint="MINT_B",
            quote_mint="SOL",
        )
        result = adapt_carbon_pumpswap_trade_v0(
            self._swap(),
            observed_at=101,
            observed_wall_ns=101_000_000_000,
            pool_observations=(),
            pool_identity_observations=(a, b),
        )
        self.assertEqual(result.status, CONFLICTING_CONTEXT)
        self.assertIsNone(result.observation)

    def test_state_and_account_identity_disagreement_fails_closed(self):
        identity = self._identity(quote_mint="DIFFERENT_QUOTE")
        result = adapt_carbon_pumpswap_trade_v0(
            self._swap(),
            observed_at=101,
            observed_wall_ns=101_000_000_000,
            pool_observations=(self._pool(quote_mint="USDC_MINT"),),
            pool_identity_observations=(identity,),
        )
        self.assertEqual(result.status, CONFLICTING_CONTEXT)

    def test_output_has_no_score_confidence_or_recommendation(self):
        result = adapt_carbon_pump_trade_v0(self._pump(), observed_at=101)
        forbidden = {"score", "confidence", "recommendation", "take", "skip"}
        self.assertTrue(forbidden.isdisjoint(result.__dataclass_fields__))


if __name__ == "__main__":
    unittest.main()
