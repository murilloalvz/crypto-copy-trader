import unittest

from src.carbon_matched_unit_adapter import (
    ADAPTED as MATCHED_UNIT_ADAPTED,
    MISSING_CONTEXT,
    adapt_carbon_pumpswap_trade_v0,
)
from src.carbon_protocol_adapter import (
    ADAPTED,
    INVALID_EVENT,
    UNSUPPORTED_EVENT,
    adapt_carbon_pumpswap_create_pool_v0,
)


class CarbonProtocolAdapterV0Tests(unittest.TestCase):
    def _create_pool(self, **overrides):
        row = dict(
            status="decoded",
            event_type="pumpswap_create_pool",
            event_key="pumpswap:create:0",
            pool="POOL_A",
            base_mint="MINT_A",
            quote_mint="USDC_MINT",
            timestamp=100,
        )
        row.update(overrides)
        return row

    def _buy(self, **overrides):
        row = dict(
            status="decoded",
            event_type="pumpswap_buy",
            event_key="pumpswap:buy:0",
            pool="POOL_A",
            side="buy",
            timestamp=101,
            quote_amount_raw=10,
            pool_quote_token_reserves_raw=200,
        )
        row.update(overrides)
        return row

    def test_create_pool_adapts_only_explicit_protocol_identity(self):
        result = adapt_carbon_pumpswap_create_pool_v0(
            self._create_pool(), observed_at=102
        )

        self.assertEqual(result.status, ADAPTED)
        self.assertEqual(result.provenance_keys, ("pumpswap:create:0",))
        self.assertEqual(result.data_quality_flags, ())
        observation = result.pool_observation
        self.assertIsNotNone(observation)
        assert observation is not None
        self.assertEqual(observation.token_mint, "MINT_A")
        self.assertEqual(observation.base_mint, "MINT_A")
        self.assertEqual(observation.quote_mint, "USDC_MINT")
        self.assertEqual(observation.pool, "POOL_A")
        self.assertEqual(observation.chain_time, 100)
        self.assertEqual(observation.observed_at, 102)
        self.assertEqual(observation.evidence_key, "pumpswap:create:0")
        self.assertEqual(observation.source, "carbon_pumpswap_create_pool_event")
        self.assertIsNone(observation.pool_index)
        self.assertIsNone(observation.pool_quote_token_reserves)
        self.assertIsNone(observation.virtual_quote_reserves)

    def test_non_create_pool_event_is_unsupported_not_inferred(self):
        result = adapt_carbon_pumpswap_create_pool_v0(
            self._create_pool(event_type="pumpswap_buy"), observed_at=102
        )
        self.assertEqual(result.status, UNSUPPORTED_EVENT)
        self.assertIsNone(result.pool_observation)

    def test_missing_or_invalid_identity_fails_closed(self):
        cases = (
            self._create_pool(event_key=None),
            self._create_pool(pool=None),
            self._create_pool(base_mint=None),
            self._create_pool(quote_mint=None),
            self._create_pool(timestamp=-1),
        )
        for row in cases:
            with self.subTest(row=row):
                result = adapt_carbon_pumpswap_create_pool_v0(row, observed_at=102)
                self.assertEqual(result.status, INVALID_EVENT)
                self.assertIsNone(result.pool_observation)

    def test_observed_at_before_chain_time_fails_closed(self):
        result = adapt_carbon_pumpswap_create_pool_v0(
            self._create_pool(), observed_at=99
        )
        self.assertEqual(result.status, INVALID_EVENT)
        self.assertIsNone(result.pool_observation)

    def test_invalid_observed_at_argument_raises(self):
        for observed_at in (-1, True, 1.5):
            with self.subTest(observed_at=observed_at):
                with self.assertRaises(ValueError):
                    adapt_carbon_pumpswap_create_pool_v0(
                        self._create_pool(), observed_at=observed_at
                    )

    def test_create_pool_context_causally_feeds_matched_unit_pumpswap_trade(self):
        pool_result = adapt_carbon_pumpswap_create_pool_v0(
            self._create_pool(), observed_at=100
        )
        self.assertEqual(pool_result.status, ADAPTED)
        assert pool_result.pool_observation is not None

        trade_result = adapt_carbon_pumpswap_trade_v0(
            self._buy(),
            observed_at=102,
            pool_observations=(pool_result.pool_observation,),
        )

        self.assertEqual(trade_result.status, MATCHED_UNIT_ADAPTED)
        observation = trade_result.observation
        self.assertIsNotNone(observation)
        assert observation is not None
        self.assertEqual(observation.token_mint, "MINT_A")
        self.assertEqual(observation.quote_asset_key, "USDC_MINT")
        self.assertEqual(observation.market_surface_key, "pumpswap:POOL_A")
        self.assertEqual(
            trade_result.provenance_keys,
            ("pumpswap:buy:0", "pumpswap:create:0"),
        )

    def test_future_create_pool_observation_is_not_backfilled_into_trade(self):
        pool_result = adapt_carbon_pumpswap_create_pool_v0(
            self._create_pool(timestamp=90), observed_at=103
        )
        self.assertEqual(pool_result.status, ADAPTED)
        assert pool_result.pool_observation is not None

        trade_result = adapt_carbon_pumpswap_trade_v0(
            self._buy(timestamp=100),
            observed_at=101,
            pool_observations=(pool_result.pool_observation,),
        )
        self.assertEqual(trade_result.status, MISSING_CONTEXT)
        self.assertIsNone(trade_result.observation)


if __name__ == "__main__":
    unittest.main()
