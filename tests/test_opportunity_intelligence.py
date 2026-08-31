import unittest

from src.discovery.models import WaveTokenSnapshot
from src.opportunity_intelligence import (
    WalletActionObservation,
    WaveOpportunityEvidence,
    build_opportunity_context,
    build_wallet_opportunity_context,
)
from src.social_intelligence import SocialEvent


def market_token(token_mint="T") -> WaveTokenSnapshot:
    return WaveTokenSnapshot(
        token=token_mint,
        name="Token",
        symbol="TKN",
        price_usd=1.0,
        liquidity_usd=100_000,
        market_cap_usd=500_000,
        created_at_ms=1,
        holders=100,
        buys=60,
        sells=40,
        total_transactions=100,
        volume_5m_usd=12_000,
        volume_1h_usd=60_000,
        volume_24h_usd=600_000,
        top10_pct=20,
        dev_pct=2,
        insiders_pct=3,
        snipers_pct=4,
        risk_score=2,
        lp_burn_pct=100,
        mint_authority=None,
        freeze_authority=None,
        market="test",
        pool_address="pool",
    )


class OpportunityIntelligenceTests(unittest.TestCase):
    def test_future_wallet_observation_is_not_available_to_past_context(self):
        observations = [
            WalletActionObservation("A", "T", "buy", chain_time=100, observed_at=130),
            WalletActionObservation("B", "T", "buy", chain_time=120, observed_at=170),
        ]

        early = build_wallet_opportunity_context(observations, token_mint="T", as_of=150)
        later = build_wallet_opportunity_context(observations, token_mint="T", as_of=200)

        self.assertEqual(early.unique_buy_wallet_count, 1)
        self.assertEqual(later.unique_buy_wallet_count, 2)

    def test_backfilled_chain_time_cannot_be_claimed_before_observation(self):
        observations = [
            WalletActionObservation("A", "T", "buy", chain_time=100, observed_at=1_000)
        ]

        context = build_wallet_opportunity_context(observations, token_mint="T", as_of=500)

        self.assertEqual(context.observed_action_count, 0)

    def test_rejects_impossible_wallet_observation_timestamp(self):
        with self.assertRaises(ValueError):
            build_wallet_opportunity_context(
                [WalletActionObservation("A", "T", "buy", 200, 100)],
                token_mint="T",
                as_of=300,
            )

    def test_context_joins_channels_without_creating_trading_score(self):
        wave = WaveOpportunityEvidence(1, "T", 900, 70.0, "wave_v3_volume_integrity")
        wallets = [WalletActionObservation("A", "T", "buy", 920, 930)]
        social = [SocialEvent("x", "1", "alice", 940, 950, token_mint="T")]

        context = build_opportunity_context(
            token_mint="T",
            as_of=1_000,
            wave=wave,
            wallet_observations=wallets,
            social_events=social,
        )

        self.assertEqual(context.available_channels, ("wave", "wallets", "social"))
        self.assertEqual(context.wallets.unique_buy_wallet_count, 1)
        self.assertEqual(context.social.current_event_count, 1)
        self.assertIsNone(context.market_integrity)
        self.assertFalse(hasattr(context, "score"))

    def test_market_integrity_is_context_not_trading_score(self):
        context = build_opportunity_context(
            token_mint="T",
            as_of=1_000,
            market_snapshot=market_token(),
            include_social=False,
        )

        self.assertEqual(context.available_channels, ("market_integrity",))
        self.assertAlmostEqual(context.market_integrity.buy_pressure_pct, 60.0)
        self.assertFalse(hasattr(context.market_integrity, "score"))

    def test_market_snapshot_must_match_token(self):
        with self.assertRaises(ValueError):
            build_opportunity_context(
                token_mint="T",
                as_of=1_000,
                market_snapshot=market_token("OTHER"),
            )

    def test_future_wave_is_excluded_until_detected(self):
        wave = WaveOpportunityEvidence(1, "T", 1_100, 70.0, "wave_v3_volume_integrity")

        context = build_opportunity_context(token_mint="T", as_of=1_000, wave=wave)

        self.assertIsNone(context.wave)
        self.assertNotIn("wave", context.available_channels)


if __name__ == "__main__":
    unittest.main()
