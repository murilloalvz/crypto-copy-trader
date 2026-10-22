import unittest

from src.wallet_forward_convergence import (
    build_forward_wallet_convergence_events,
    summarize_forward_wallet_convergence,
)
from src.wallet_quote_watch import ForwardBuyEvent


def buy(
    event_id: int,
    wallet: str,
    token: str,
    observed_at: int,
    *,
    chain_time: int | None = None,
) -> ForwardBuyEvent:
    return ForwardBuyEvent(
        id=event_id,
        observation_key=f"obs-{event_id}",
        wallet_address=wallet,
        token_mint=token,
        chain_time=observed_at - 5 if chain_time is None else chain_time,
        observed_at=observed_at,
    )


class WalletForwardConvergenceTests(unittest.TestCase):
    def test_second_unique_wallet_triggers_causal_convergence(self):
        events = [
            buy(1, "A", "T", 100),
            buy(2, "A", "T", 120),
            buy(3, "B", "T", 150, chain_time=130),
        ]

        result = build_forward_wallet_convergence_events(
            events,
            window_seconds=60,
            min_unique_buy_wallets=2,
        )

        self.assertEqual(len(result), 1)
        event = result[0]
        self.assertEqual(event.trigger_event_id, 3)
        self.assertEqual(event.trigger_observation_key, "obs-3")
        self.assertEqual(event.triggered_at, 150)
        self.assertEqual(event.participating_wallets, ("A", "B"))
        self.assertEqual(event.convergence_span_seconds, 50)
        self.assertEqual(event.trigger_source_lag_seconds, 20)

    def test_same_wallet_repeats_do_not_create_confirmation(self):
        result = build_forward_wallet_convergence_events(
            [buy(1, "A", "T", 100), buy(2, "A", "T", 120), buy(3, "A", "T", 140)],
            window_seconds=60,
        )

        self.assertEqual(result, ())

    def test_future_wallet_cannot_confirm_past_event(self):
        events = [buy(1, "A", "T", 100), buy(2, "B", "T", 500)]

        result = build_forward_wallet_convergence_events(events, window_seconds=300)

        self.assertEqual(result, ())

    def test_threshold_crossing_emits_once_inside_same_burst(self):
        events = [
            buy(1, "A", "T", 100),
            buy(2, "B", "T", 120),
            buy(3, "C", "T", 140),
            buy(4, "A", "T", 160),
        ]

        result = build_forward_wallet_convergence_events(events, window_seconds=300)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].trigger_event_id, 2)
        self.assertEqual(result[0].unique_buy_wallet_count, 2)

    def test_token_cooldown_prevents_repeated_sample_inflation(self):
        events = [
            buy(1, "A", "T", 100),
            buy(2, "B", "T", 120),
            buy(3, "A", "T", 600),
            buy(4, "B", "T", 620),
            buy(5, "A", "T", 2200),
            buy(6, "B", "T", 2220),
        ]

        result = build_forward_wallet_convergence_events(
            events,
            window_seconds=300,
            token_cooldown_seconds=1800,
        )

        self.assertEqual([item.trigger_event_id for item in result], [2, 6])

    def test_different_tokens_have_independent_convergence(self):
        result = build_forward_wallet_convergence_events(
            [
                buy(1, "A", "T1", 100),
                buy(2, "B", "T1", 110),
                buy(3, "A", "T2", 120),
                buy(4, "B", "T2", 130),
            ]
        )

        self.assertEqual({item.token_mint for item in result}, {"T1", "T2"})

    def test_summary_keeps_observability_separate_from_edge(self):
        buys = [
            buy(1, "A", "T", 100, chain_time=90),
            buy(2, "B", "T", 110, chain_time=100),
        ]
        convergence = build_forward_wallet_convergence_events(buys)

        summary = summarize_forward_wallet_convergence(buys, convergence)

        self.assertEqual(summary.buy_event_count, 2)
        self.assertEqual(summary.buy_wallet_count, 2)
        self.assertEqual(summary.convergence_event_count, 1)
        self.assertEqual(summary.convergence_token_count, 1)
        self.assertEqual(summary.median_trigger_source_lag_seconds, 10.0)
        self.assertFalse(hasattr(summary, "edge"))
        self.assertFalse(hasattr(summary, "pnl"))

    def test_invalid_observation_time_is_rejected(self):
        with self.assertRaises(ValueError):
            build_forward_wallet_convergence_events(
                [buy(1, "A", "T", 100, chain_time=101)]
            )


if __name__ == "__main__":
    unittest.main()
