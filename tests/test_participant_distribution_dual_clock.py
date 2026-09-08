import unittest

from src.market_opportunity_radar import MarketTradeObservation
from src.participant_distribution_research import build_participant_distribution_window


def _trade(*, wallet: str, chain_time: int, observed_at: int) -> MarketTradeObservation:
    return MarketTradeObservation(
        token_mint="TOKEN",
        side="buy",
        chain_time=chain_time,
        observed_at=observed_at,
        wallet_address=wallet,
        transaction_key=f"{wallet}-{chain_time}",
    )


class ParticipantDistributionDualClockTests(unittest.TestCase):
    def test_market_anchor_prevents_pipeline_latency_from_shifting_window(self):
        result = build_participant_distribution_window(
            token_mint="TOKEN",
            market_anchor_time=100,
            as_of=110,
            window_seconds=30,
            observations=[
                _trade(wallet="PRE", chain_time=75, observed_at=76),
                _trade(wallet="POST", chain_time=105, observed_at=106),
            ],
        )
        self.assertEqual(result.market_anchor_time, 100)
        self.assertEqual(result.as_of, 110)
        self.assertEqual(result.market_event_count, 1)
        self.assertEqual(result.known_unique_buy_wallet_count, 1)

    def test_event_inside_market_window_but_unknown_by_decision_is_excluded(self):
        result = build_participant_distribution_window(
            token_mint="TOKEN",
            market_anchor_time=100,
            as_of=105,
            window_seconds=30,
            observations=[
                _trade(wallet="KNOWN", chain_time=90, observed_at=95),
                _trade(wallet="LATE", chain_time=95, observed_at=106),
            ],
        )
        self.assertEqual(result.market_event_count, 1)
        self.assertEqual(result.known_unique_buy_wallet_count, 1)

    def test_market_anchor_after_knowledge_cutoff_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "market_anchor_time"):
            build_participant_distribution_window(
                token_mint="TOKEN",
                market_anchor_time=101,
                as_of=100,
                window_seconds=30,
                observations=[],
            )


if __name__ == "__main__":
    unittest.main()
