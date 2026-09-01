import unittest

from src.causal_quotes import CausalQuoteObservation
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_economic_replay import EconomicReplayConfig, replay_source_wallet, summarize_economic_replay


W = "wallet"
T = "token"
SOL = "sol"


def q(side, at, price):
    return CausalQuoteObservation(T, side, at, at, price, "jupiter", True,
                                  input_mint=SOL if side == "buy" else T,
                                  output_mint=T if side == "buy" else SOL)


class EconomicReplayTests(unittest.TestCase):
    def test_buy_sell_is_closed_with_cost(self):
        actions = [WalletActionObservation(W, T, "buy", 100, 100), WalletActionObservation(W, T, "sell", 200, 200)]
        trades = replay_source_wallet(actions, [q("buy", 100, 10), q("sell", 200, 12)])
        self.assertEqual(trades[0].status, "CLOSED")
        self.assertAlmostEqual(trades[0].net_return_pct, 17.62, places=2)

    def test_sell_before_buy_is_preexisting_and_not_a_trade(self):
        actions = [WalletActionObservation(W, T, "sell", 100, 100), WalletActionObservation(W, T, "buy", 200, 200)]
        trades = replay_source_wallet(actions, [q("sell", 100, 12), q("buy", 200, 10)])
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].status, "OPEN")

    def test_missing_sell_is_censored(self):
        actions = [WalletActionObservation(W, T, "buy", 100, 100)]
        trades = replay_source_wallet(actions, [q("buy", 100, 10)])
        self.assertEqual(trades[0].status, "OPEN")
        self.assertIn("censored", trades[0].flags)

    def test_missing_exit_quote_never_creates_pnl(self):
        actions = [WalletActionObservation(W, T, "buy", 100, 100), WalletActionObservation(W, T, "sell", 200, 200)]
        trades = replay_source_wallet(actions, [q("buy", 100, 10)])
        self.assertEqual(trades[0].status, "CENSORED")
        self.assertIsNone(trades[0].pnl_usd)

    def test_delay_is_causal(self):
        actions = [WalletActionObservation(W, T, "buy", 100, 100), WalletActionObservation(W, T, "sell", 200, 200)]
        quotes = [q("buy", 100, 10), q("buy", 120, 11), q("sell", 200, 12)]
        trades = replay_source_wallet(actions, quotes, config=EconomicReplayConfig(delays=(0, 15)))
        self.assertEqual(trades[0].entry_price_usd, 10)
        trades = replay_source_wallet(actions, quotes, config=EconomicReplayConfig(delays=(15,)), delay_seconds=15)
        self.assertEqual(trades[0].entry_price_usd, 11)

    def test_summary_exposes_clusters(self):
        actions = [WalletActionObservation(W, T, "buy", 100, 100)]
        trades = replay_source_wallet(actions, [q("buy", 100, 10)])
        summary = summarize_economic_replay(trades, buy_count=1)
        self.assertEqual(summary.cluster_count, 1)
        self.assertEqual(summary.censored_count, 0)


if __name__ == "__main__":
    unittest.main()
