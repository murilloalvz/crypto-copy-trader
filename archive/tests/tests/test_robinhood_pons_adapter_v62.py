import unittest

from src.robinhood_pons_adapter_v62 import (
    PonsCurveTradeV62,
    PonsLaunchV62,
    PonsLifecycleEventV62,
    build_stage_snapshot_v62,
    curve_trade_to_v59,
    graduation_to_v59,
    launch_to_v59,
    threshold_quote_units_v62,
)


TOKEN = "0x1111111111111111111111111111111111111111"
CURVE = "0x2222222222222222222222222222222222222222"
DEPLOYER = "0x3333333333333333333333333333333333333333"
PAIR = "0x4444444444444444444444444444444444444444"
WALLET = "0x5555555555555555555555555555555555555555"
TX1 = "0x" + "11" * 32
TX2 = "0x" + "22" * 32
TX3 = "0x" + "33" * 32
TX4 = "0x" + "44" * 32


def launch(**overrides):
    values = dict(
        token_address=TOKEN,
        curve_address=CURVE,
        deployer_address=DEPLOYER,
        pair_token_address=PAIR,
        graduation_threshold_raw=4_200_000_000_000_000_000,
        pair_token_decimals=18,
        chain_time=100,
        observed_at=101,
        transaction_hash=TX1,
        block_number=10,
        event_index=1,
    )
    values.update(overrides)
    return PonsLaunchV62(**values)


class RobinhoodPonsAdapterV62Tests(unittest.TestCase):
    def test_launch_maps_to_robinhood_market_start_without_solana_semantics(self):
        item = launch_to_v59(launch(), source_provider="pons_v2_events")
        self.assertEqual(item.asset.network.namespace, "eip155")
        self.assertEqual(item.asset.network.reference, "4663")
        self.assertEqual(item.asset.address, TOKEN)
        self.assertEqual(item.event_type, "market_started")
        self.assertEqual(item.venue, "pons_v2_curve")
        self.assertEqual(item.transaction_key, TX1)

    def test_graduation_threshold_is_launch_specific_not_hardcoded_to_4_2_eth(self):
        usd_like = launch(
            graduation_threshold_raw=8_090_000_000,
            pair_token_decimals=6,
        )
        self.assertEqual(threshold_quote_units_v62(usd_like), 8090.0)
        self.assertNotEqual(threshold_quote_units_v62(usd_like), 4.2)

    def test_curve_trade_preserves_wallet_chain_position_and_optional_economics(self):
        trade = PonsCurveTradeV62(
            token_address=TOKEN,
            curve_address=CURVE,
            wallet_address=WALLET,
            side="buy",
            token_amount_raw=123,
            quote_amount_raw=456,
            quote_decimals=18,
            chain_time=105,
            observed_at=106,
            transaction_hash=TX2,
            block_number=11,
            event_index=7,
            notional_usd=25.0,
            price_usd=0.0001,
        )
        item = curve_trade_to_v59(trade, source_provider="pons_v2_events")
        self.assertEqual(item.side, "buy")
        self.assertEqual(item.wallet_address, WALLET)
        self.assertEqual(item.block_number, 11)
        self.assertEqual(item.event_index, 7)
        self.assertEqual(item.notional_usd, 25.0)
        self.assertEqual(item.price_usd, 0.0001)
        self.assertEqual(item.venue, "pons_v2_curve")

    def test_swept_phase_is_not_misrepresented_as_completed_graduation(self):
        swept = PonsLifecycleEventV62(
            token_address=TOKEN,
            phase="launch_swept",
            chain_time=120,
            observed_at=121,
            transaction_hash=TX3,
            block_number=12,
            event_index=2,
        )
        with self.assertRaisesRegex(ValueError, "only pool_graduated"):
            graduation_to_v59(swept, source_provider="pons_v2_events")

    def test_stage_between_sweep_and_pool_creation_is_explicitly_not_tradable(self):
        swept = PonsLifecycleEventV62(
            token_address=TOKEN,
            phase="launch_swept",
            chain_time=120,
            observed_at=121,
            transaction_hash=TX3,
            block_number=12,
            event_index=2,
        )
        graduated = PonsLifecycleEventV62(
            token_address=TOKEN,
            phase="pool_graduated",
            chain_time=140,
            observed_at=141,
            transaction_hash=TX4,
            block_number=14,
            event_index=4,
        )
        snapshot = build_stage_snapshot_v62(
            launch=launch(), lifecycle_events=[swept, graduated], as_of=130
        )
        self.assertEqual(snapshot.stage, "SWEPT_NOT_TRADABLE")
        self.assertFalse(snapshot.market_tradable)
        self.assertTrue(snapshot.sweep_known)
        self.assertFalse(snapshot.graduation_known)

    def test_historical_graduation_discovered_late_cannot_leak_into_earlier_as_of(self):
        graduated = PonsLifecycleEventV62(
            token_address=TOKEN,
            phase="pool_graduated",
            chain_time=125,
            observed_at=160,
            transaction_hash=TX4,
            block_number=13,
            event_index=4,
        )
        snapshot = build_stage_snapshot_v62(
            launch=launch(), lifecycle_events=[graduated], as_of=140
        )
        self.assertEqual(snapshot.stage, "CURVE_TRADING")
        self.assertFalse(snapshot.graduation_known)

    def test_completed_graduation_maps_to_v59_only_after_observation(self):
        graduated = PonsLifecycleEventV62(
            token_address=TOKEN,
            phase="pool_graduated",
            chain_time=140,
            observed_at=141,
            transaction_hash=TX4,
            block_number=14,
            event_index=4,
        )
        item = graduation_to_v59(graduated, source_provider="pons_v2_events")
        self.assertEqual(item.event_type, "graduated")
        self.assertEqual(item.venue, "uniswap_v4")
        self.assertEqual(item.prior_venue, "pons_v2_swept_not_tradable")

    def test_invalid_observation_clock_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot precede"):
            launch_to_v59(
                launch(chain_time=100, observed_at=99),
                source_provider="pons_v2_events",
            )


if __name__ == "__main__":
    unittest.main()
