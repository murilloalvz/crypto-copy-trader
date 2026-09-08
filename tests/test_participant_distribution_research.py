import unittest

from src.market_opportunity_radar import MarketTradeObservation
from src.participant_distribution_research import build_participant_distribution_window


def _trade(
    *,
    wallet: str | None,
    side: str,
    chain_time: int,
    observed_at: int | None = None,
    token: str = "TOKEN",
    tx: str | None = None,
) -> MarketTradeObservation:
    return MarketTradeObservation(
        token_mint=token,
        side=side,
        chain_time=chain_time,
        observed_at=chain_time if observed_at is None else observed_at,
        wallet_address=wallet,
        transaction_key=tx,
    )


class ParticipantDistributionResearchTests(unittest.TestCase):
    def test_distributed_buyers_have_low_concentration(self):
        result = build_participant_distribution_window(
            token_mint="TOKEN",
            as_of=100,
            window_seconds=60,
            observations=[
                _trade(wallet="A", side="buy", chain_time=70, tx="1"),
                _trade(wallet="B", side="buy", chain_time=80, tx="2"),
                _trade(wallet="C", side="buy", chain_time=90, tx="3"),
                _trade(wallet="D", side="buy", chain_time=95, tx="4"),
            ],
        )
        self.assertEqual(result.buy_event_count, 4)
        self.assertEqual(result.known_unique_buy_wallet_count, 4)
        self.assertEqual(result.buyer_wallet_identity_coverage_pct, 100.0)
        self.assertEqual(result.buyer_breadth_ratio, 1.0)
        self.assertEqual(result.buyer_repeated_event_share_pct, 0.0)
        self.assertEqual(result.top1_buyer_event_share_pct, 25.0)
        self.assertEqual(result.top3_buyer_event_share_pct, 75.0)
        self.assertAlmostEqual(result.participant_buy_event_hhi or 0.0, 0.25)

    def test_concentrated_buyers_have_higher_hhi_and_repetition(self):
        result = build_participant_distribution_window(
            token_mint="TOKEN",
            as_of=100,
            window_seconds=60,
            observations=[
                _trade(wallet="A", side="buy", chain_time=70, tx="1"),
                _trade(wallet="A", side="buy", chain_time=80, tx="2"),
                _trade(wallet="A", side="buy", chain_time=90, tx="3"),
                _trade(wallet="B", side="buy", chain_time=95, tx="4"),
            ],
        )
        self.assertEqual(result.known_unique_buy_wallet_count, 2)
        self.assertEqual(result.buyer_breadth_ratio, 0.5)
        self.assertEqual(result.buyer_repeated_event_share_pct, 50.0)
        self.assertEqual(result.top1_buyer_event_share_pct, 75.0)
        self.assertEqual(result.top3_buyer_event_share_pct, 100.0)
        self.assertAlmostEqual(result.participant_buy_event_hhi or 0.0, 0.625)

    def test_partial_buyer_identity_keeps_structural_metrics_missing(self):
        result = build_participant_distribution_window(
            token_mint="TOKEN",
            as_of=100,
            window_seconds=60,
            observations=[
                _trade(wallet="A", side="buy", chain_time=80),
                _trade(wallet=None, side="buy", chain_time=90),
            ],
        )
        self.assertEqual(result.buyer_wallet_identity_coverage_pct, 50.0)
        self.assertEqual(result.known_unique_buy_wallet_count, 1)
        self.assertIsNone(result.buyer_breadth_ratio)
        self.assertIsNone(result.buyer_repeated_event_share_pct)
        self.assertIsNone(result.top1_buyer_event_share_pct)
        self.assertIsNone(result.top3_buyer_event_share_pct)
        self.assertIsNone(result.participant_buy_event_hhi)
        self.assertIn("partial_buyer_wallet_identity_coverage", result.data_quality_flags)
        self.assertIn(
            "buyer_structural_metrics_unavailable_due_to_partial_identity",
            result.data_quality_flags,
        )

    def test_late_observed_trade_cannot_be_backfilled(self):
        result = build_participant_distribution_window(
            token_mint="TOKEN",
            as_of=100,
            window_seconds=60,
            observations=[
                _trade(wallet="A", side="buy", chain_time=90, observed_at=101),
                _trade(wallet="B", side="buy", chain_time=95, observed_at=99),
            ],
        )
        self.assertEqual(result.market_event_count, 1)
        self.assertEqual(result.buy_event_count, 1)
        self.assertEqual(result.known_unique_buy_wallet_count, 1)
        self.assertEqual(result.top1_buyer_event_share_pct, 100.0)

    def test_window_and_token_membership_are_causal_and_specific(self):
        result = build_participant_distribution_window(
            token_mint="TOKEN",
            as_of=100,
            window_seconds=30,
            observations=[
                _trade(wallet="OLD", side="buy", chain_time=70, observed_at=70),
                _trade(wallet="IN", side="buy", chain_time=71, observed_at=72),
                _trade(wallet="OTHER", side="buy", chain_time=90, token="OTHER"),
                _trade(wallet="SELLER", side="sell", chain_time=99),
            ],
        )
        self.assertEqual(result.market_event_count, 2)
        self.assertEqual(result.buy_event_count, 1)
        self.assertEqual(result.sell_event_count, 1)
        self.assertEqual(result.known_unique_market_wallet_count, 2)
        self.assertEqual(result.known_unique_buy_wallet_count, 1)

    def test_no_buy_events_have_no_buyer_structure(self):
        result = build_participant_distribution_window(
            token_mint="TOKEN",
            as_of=100,
            window_seconds=60,
            observations=[_trade(wallet="S", side="sell", chain_time=90)],
        )
        self.assertEqual(result.buy_event_count, 0)
        self.assertIsNone(result.buyer_wallet_identity_coverage_pct)
        self.assertIsNone(result.buyer_breadth_ratio)
        self.assertIsNone(result.participant_buy_event_hhi)
        self.assertIn("no_buy_events_in_window", result.data_quality_flags)

    def test_epistemic_boundaries_are_explicit(self):
        result = build_participant_distribution_window(
            token_mint="TOKEN",
            as_of=100,
            window_seconds=60,
            observations=[_trade(wallet="A", side="buy", chain_time=90)],
        )
        self.assertIn(
            "distinct_addresses_are_not_independent_traders",
            result.epistemic_cautions,
        )
        self.assertIn(
            "participant_concentration_is_descriptive_not_manipulation_evidence",
            result.epistemic_cautions,
        )
        self.assertIn(
            "participant_repetition_is_descriptive_not_wash_trading_evidence",
            result.epistemic_cautions,
        )

    def test_invalid_observation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "trade side"):
            build_participant_distribution_window(
                token_mint="TOKEN",
                as_of=100,
                window_seconds=60,
                observations=[
                    MarketTradeObservation(
                        token_mint="TOKEN",
                        side="unknown",
                        chain_time=90,
                        observed_at=90,
                        wallet_address="A",
                    )
                ],
            )


if __name__ == "__main__":
    unittest.main()
