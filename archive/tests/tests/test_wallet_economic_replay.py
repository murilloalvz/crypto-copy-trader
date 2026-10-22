import unittest
from types import SimpleNamespace

from src.causal_quotes import CausalQuoteObservation
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_economic_replay import (
    EconomicReplayConfig,
    replay_source_wallet,
    summarize_economic_replay,
)


W = "wallet"
T = "token"
SOL = "sol"


def q(side, at, price, token=T):
    return CausalQuoteObservation(
        token,
        side,
        at,
        at,
        price,
        "jupiter",
        True,
        input_mint=SOL if side == "buy" else token,
        output_mint=token if side == "buy" else SOL,
    )


def qa(
    side,
    at,
    *,
    delta,
    before,
    after,
    key,
    token=T,
    wallet=W,
    eligible=True,
    reduction=None,
):
    return SimpleNamespace(
        address=wallet,
        token_mint=token,
        side=side,
        chain_time=at,
        observed_at=at,
        observation_key=key,
        economic_eligible=eligible,
        token_delta_raw=None if delta is None else str(delta),
        token_balance_before_raw=None if before is None else str(before),
        token_balance_after_raw=None if after is None else str(after),
        source_reduction_fraction=reduction,
    )


def event_quotes(*pairs):
    return {key: tuple(values) for key, values in pairs}


class EconomicReplayTests(unittest.TestCase):
    def test_buy_sell_is_closed_with_cost(self):
        actions = [
            WalletActionObservation(W, T, "buy", 100, 100),
            WalletActionObservation(W, T, "sell", 200, 200),
        ]
        trades = replay_source_wallet(actions, [q("buy", 100, 10), q("sell", 200, 12)])
        self.assertEqual(trades[0].status, "CLOSED")
        self.assertAlmostEqual(trades[0].net_return_pct, 17.62, places=2)

    def test_sell_before_buy_is_preexisting_and_not_a_trade(self):
        actions = [
            WalletActionObservation(W, T, "sell", 100, 100),
            WalletActionObservation(W, T, "buy", 200, 200),
        ]
        trades = replay_source_wallet(actions, [q("sell", 100, 12), q("buy", 200, 10)])
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].status, "OPEN")

    def test_missing_sell_is_censored(self):
        actions = [WalletActionObservation(W, T, "buy", 100, 100)]
        trades = replay_source_wallet(actions, [q("buy", 100, 10)])
        self.assertEqual(trades[0].status, "OPEN")
        self.assertIn("censored", trades[0].flags)

    def test_missing_exit_quote_never_creates_pnl(self):
        actions = [
            WalletActionObservation(W, T, "buy", 100, 100),
            WalletActionObservation(W, T, "sell", 200, 200),
        ]
        trades = replay_source_wallet(actions, [q("buy", 100, 10)])
        self.assertEqual(trades[0].status, "CENSORED")
        self.assertIsNone(trades[0].pnl_usd)

    def test_delay_is_causal(self):
        actions = [
            WalletActionObservation(W, T, "buy", 100, 100),
            WalletActionObservation(W, T, "sell", 200, 200),
        ]
        quotes = [q("buy", 100, 10), q("buy", 120, 11), q("sell", 200, 12)]
        trades = replay_source_wallet(
            actions, quotes, config=EconomicReplayConfig(delays=(0, 15))
        )
        self.assertEqual(trades[0].entry_price_usd, 10)
        trades = replay_source_wallet(
            actions,
            quotes,
            config=EconomicReplayConfig(delays=(15,)),
            delay_seconds=15,
        )
        self.assertEqual(trades[0].entry_price_usd, 11)

    def test_summary_exposes_clusters(self):
        actions = [WalletActionObservation(W, T, "buy", 100, 100)]
        trades = replay_source_wallet(actions, [q("buy", 100, 10)])
        summary = summarize_economic_replay(trades, buy_count=1)
        self.assertEqual(summary.cluster_count, 1)
        self.assertEqual(summary.censored_count, 0)

    def test_quantity_full_sell_closes_all_repeated_buy_lots(self):
        actions = [
            qa("buy", 100, delta=50, before=0, after=50, key="b1"),
            qa("buy", 110, delta=30, before=50, after=80, key="b2"),
            qa("buy", 120, delta=20, before=80, after=100, key="b3"),
            qa("sell", 200, delta=-100, before=100, after=0, key="s1", reduction=1.0),
        ]
        by_event = event_quotes(
            ("b1", [q("buy", 100, 10)]),
            ("b2", [q("buy", 110, 11)]),
            ("b3", [q("buy", 120, 12)]),
            ("s1", [q("sell", 200, 8)]),
        )
        trades = replay_source_wallet(
            actions,
            tuple(quote for values in by_event.values() for quote in values),
            quotes_by_event=by_event,
            run_completed=True,
        )
        self.assertEqual(len(trades), 3)
        self.assertEqual(sum(t.status == "CLOSED" for t in trades), 3)
        self.assertTrue(all("source_complete_reduction" in t.flags for t in trades))

    def test_quantity_partial_then_full_uses_weighted_exit_for_each_lot(self):
        actions = [
            qa("buy", 100, delta=50, before=0, after=50, key="b1"),
            qa("buy", 110, delta=50, before=50, after=100, key="b2"),
            qa("sell", 200, delta=-50, before=100, after=50, key="s1", reduction=0.5),
            qa("sell", 300, delta=-50, before=50, after=0, key="s2", reduction=1.0),
        ]
        by_event = event_quotes(
            ("b1", [q("buy", 100, 10)]),
            ("b2", [q("buy", 110, 20)]),
            ("s1", [q("sell", 200, 12)]),
            ("s2", [q("sell", 300, 8)]),
        )
        trades = replay_source_wallet(
            actions,
            tuple(quote for values in by_event.values() for quote in values),
            quotes_by_event=by_event,
            run_completed=True,
        )
        self.assertEqual([round(t.exit_price_usd, 6) for t in trades], [10.0, 10.0])
        self.assertTrue(all(t.status == "CLOSED" for t in trades))
        self.assertTrue(all("source_proportional_reduction" in t.flags for t in trades))

    def test_partial_sell_with_preexisting_inventory_is_censored(self):
        actions = [
            qa("buy", 100, delta=50, before=100, after=150, key="b1"),
            qa("sell", 200, delta=-50, before=150, after=100, key="s1", reduction=1 / 3),
        ]
        by_event = event_quotes(
            ("b1", [q("buy", 100, 10)]),
            ("s1", [q("sell", 200, 12)]),
        )
        trades = replay_source_wallet(
            actions,
            tuple(quote for values in by_event.values() for quote in values),
            quotes_by_event=by_event,
            run_completed=True,
        )
        self.assertEqual(trades[0].status, "CENSORED")
        self.assertEqual(trades[0].reason, "ambiguous_partial_source_sell")

    def test_full_sell_with_preexisting_inventory_can_close_forward_lot(self):
        actions = [
            qa("buy", 100, delta=50, before=100, after=150, key="b1"),
            qa("sell", 200, delta=-150, before=150, after=0, key="s1", reduction=1.0),
        ]
        by_event = event_quotes(
            ("b1", [q("buy", 100, 10)]),
            ("s1", [q("sell", 200, 12)]),
        )
        trades = replay_source_wallet(
            actions,
            tuple(quote for values in by_event.values() for quote in values),
            quotes_by_event=by_event,
            run_completed=True,
        )
        self.assertEqual(trades[0].status, "CLOSED")

    def test_followup_only_buy_becomes_noncopy_inventory_and_is_not_a_trade(self):
        actions = [
            qa("buy", 100, delta=50, before=0, after=50, key="enrolled"),
            qa("buy", 150, delta=50, before=50, after=100, key="followup", eligible=False),
            qa("sell", 200, delta=-50, before=100, after=50, key="sell", reduction=0.5),
        ]
        by_event = event_quotes(
            ("enrolled", [q("buy", 100, 10)]),
            ("sell", [q("sell", 200, 12)]),
        )
        trades = replay_source_wallet(
            actions,
            tuple(quote for values in by_event.values() for quote in values),
            quotes_by_event=by_event,
            run_completed=True,
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].status, "CENSORED")
        self.assertEqual(trades[0].reason, "ambiguous_partial_source_sell")

    def test_missing_quantity_on_quantity_aware_sell_censors_instead_of_fifo_fallback(self):
        actions = [
            qa("buy", 100, delta=50, before=0, after=50, key="b1"),
            qa("sell", 200, delta=None, before=None, after=None, key="s1"),
        ]
        by_event = event_quotes(("b1", [q("buy", 100, 10)]))
        trades = replay_source_wallet(
            actions,
            tuple(quote for values in by_event.values() for quote in values),
            quotes_by_event=by_event,
            run_completed=True,
        )
        self.assertEqual(trades[0].status, "CENSORED")
        self.assertEqual(trades[0].reason, "source_quantity_unknown_on_sell")

    def test_missing_sell_quote_on_full_reduction_censors_all_lots(self):
        actions = [
            qa("buy", 100, delta=50, before=0, after=50, key="b1"),
            qa("buy", 110, delta=50, before=50, after=100, key="b2"),
            qa("sell", 200, delta=-100, before=100, after=0, key="s1", reduction=1.0),
        ]
        by_event = event_quotes(
            ("b1", [q("buy", 100, 10)]),
            ("b2", [q("buy", 110, 11)]),
        )
        trades = replay_source_wallet(
            actions,
            tuple(quote for values in by_event.values() for quote in values),
            quotes_by_event=by_event,
            run_completed=True,
        )
        self.assertEqual(len(trades), 2)
        self.assertTrue(all(t.status == "CENSORED" for t in trades))
        self.assertTrue(all(t.pnl_usd is None for t in trades))

    def test_wallet_and_token_inventory_never_mix(self):
        other_token = "other-token"
        actions = [
            qa("buy", 100, delta=10, before=0, after=10, key="a", token=T, wallet="w1"),
            qa("buy", 101, delta=20, before=0, after=20, key="b", token=other_token, wallet="w1"),
            qa("buy", 102, delta=30, before=0, after=30, key="c", token=T, wallet="w2"),
            qa("sell", 200, delta=-10, before=10, after=0, key="sa", token=T, wallet="w1", reduction=1.0),
        ]
        by_event = event_quotes(
            ("a", [q("buy", 100, 10, T)]),
            ("b", [q("buy", 101, 20, other_token)]),
            ("c", [q("buy", 102, 30, T)]),
            ("sa", [q("sell", 200, 12, T)]),
        )
        trades = replay_source_wallet(
            actions,
            tuple(quote for values in by_event.values() for quote in values),
            quotes_by_event=by_event,
            run_completed=True,
        )
        statuses = {(t.wallet_address, t.token_mint): t.status for t in trades}
        self.assertEqual(statuses[("w1", T)], "CLOSED")
        self.assertEqual(statuses[("w1", other_token)], "RIGHT_CENSORED")
        self.assertEqual(statuses[("w2", T)], "RIGHT_CENSORED")


if __name__ == "__main__":
    unittest.main()
