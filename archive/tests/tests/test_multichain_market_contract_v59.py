import unittest

from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation
from src.multichain_market_contract_v59 import (
    UnifiedLifecycleEventV59,
    canonical_asset_v59,
    namespaced_event_key_v59,
    solana_lifecycle_to_v59,
    solana_trade_to_v59,
    validate_lifecycle_v59,
)


class MultichainMarketContractV59Tests(unittest.TestCase):
    def test_same_native_event_key_cannot_collide_across_chains(self):
        sol = canonical_asset_v59(
            namespace="solana",
            reference="mainnet",
            address="So11111111111111111111111111111111111111112",
        )
        rh = canonical_asset_v59(
            namespace="eip155",
            reference=4663,
            address="0x1111111111111111111111111111111111111111",
        )
        self.assertNotEqual(
            namespaced_event_key_v59(sol, "tx:0"),
            namespaced_event_key_v59(rh, "tx:0"),
        )

    def test_evm_asset_identity_is_lowercase_and_chain_id_canonical(self):
        asset = canonical_asset_v59(
            namespace="EIP155",
            reference="04663",
            address="0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD",
        )
        self.assertEqual(asset.network.namespace, "eip155")
        self.assertEqual(asset.network.reference, "4663")
        self.assertEqual(asset.address, "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd")

    def test_bad_evm_address_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "20-byte"):
            canonical_asset_v59(namespace="eip155", reference=4663, address="0x123")

    def test_existing_solana_trade_is_wrapped_without_semantic_change(self):
        original = MarketTradeObservation(
            token_mint="TOKEN",
            side="buy",
            chain_time=100,
            observed_at=102,
            wallet_address="wallet",
            notional_usd=12.5,
            price_usd=0.001,
            venue="pump",
            transaction_key="sig",
        )
        wrapped = solana_trade_to_v59(
            native_event_key="native",
            source_provider="pump",
            observation=original,
        )
        self.assertEqual(wrapped.asset.network.namespace, "solana")
        self.assertEqual(wrapped.asset.network.reference, "mainnet")
        self.assertEqual(wrapped.asset.address, original.token_mint)
        self.assertEqual(wrapped.side, original.side)
        self.assertEqual(wrapped.chain_time, original.chain_time)
        self.assertEqual(wrapped.observed_at, original.observed_at)
        self.assertEqual(wrapped.wallet_address, original.wallet_address)
        self.assertEqual(wrapped.notional_usd, original.notional_usd)
        self.assertEqual(wrapped.price_usd, original.price_usd)
        self.assertEqual(wrapped.venue, original.venue)
        self.assertEqual(wrapped.transaction_key, original.transaction_key)

    def test_existing_solana_lifecycle_maps_only_to_market_started(self):
        original = MarketLifecycleObservation(
            token_mint="TOKEN",
            market_started_at=90,
            observed_at=95,
            venue="pump",
        )
        wrapped = solana_lifecycle_to_v59(
            native_event_key="launch",
            source_provider="pump",
            observation=original,
        )
        self.assertEqual(wrapped.event_type, "market_started")
        self.assertEqual(wrapped.chain_time, 90)
        self.assertEqual(wrapped.observed_at, 95)

    def test_robinhood_graduation_is_representable_without_pretending_market_start(self):
        asset = canonical_asset_v59(
            namespace="eip155",
            reference=4663,
            address="0x2222222222222222222222222222222222222222",
        )
        item = UnifiedLifecycleEventV59(
            event_key=namespaced_event_key_v59(asset, "graduated:10:2"),
            source_provider="pons_v2",
            asset=asset,
            event_type="graduated",
            chain_time=110,
            observed_at=111,
            venue="uniswap_v4",
            prior_venue="pons_v2_curve",
            transaction_key="0xabc",
            block_number=10,
            event_index=2,
        )
        validate_lifecycle_v59(item)
        self.assertEqual(item.event_type, "graduated")

    def test_lifecycle_observation_cannot_arrive_before_chain_event(self):
        asset = canonical_asset_v59(
            namespace="eip155",
            reference=4663,
            address="0x3333333333333333333333333333333333333333",
        )
        item = UnifiedLifecycleEventV59(
            event_key="x",
            source_provider="pons_v2",
            asset=asset,
            event_type="market_started",
            chain_time=200,
            observed_at=199,
        )
        with self.assertRaisesRegex(ValueError, "cannot precede"):
            validate_lifecycle_v59(item)


if __name__ == "__main__":
    unittest.main()
