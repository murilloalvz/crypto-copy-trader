import unittest

from src.wallet_forward_exposure import summarize_wallet_forward_exposure
from src.wallet_quote_watch import ForwardBuyEvent


def _event(event_id: int, observed_at: int) -> ForwardBuyEvent:
    return ForwardBuyEvent(
        id=event_id,
        observation_key=f"buy-{event_id}",
        wallet_address="A",
        token_mint=f"T{event_id}",
        chain_time=observed_at - 5,
        observed_at=observed_at,
    )


class WalletForwardExposureTests(unittest.TestCase):
    def test_followup_eligibility_uses_observed_at_not_chain_time(self):
        summary = summarize_wallet_forward_exposure(
            [_event(1, 100), _event(2, 190)],
            observation_window_end_at=200,
            horizons_seconds=[15, 60, 120],
        )

        self.assertEqual(summary.buy_count, 2)
        self.assertEqual(summary.min_remaining_observation_seconds, 10)
        self.assertEqual(summary.max_remaining_observation_seconds, 100)
        by_horizon = {item.horizon_seconds: item for item in summary.horizons}
        self.assertEqual(by_horizon[15].eligible_buy_count, 1)
        self.assertEqual(by_horizon[60].eligible_buy_count, 1)
        self.assertEqual(by_horizon[120].eligible_buy_count, 0)
        self.assertEqual(by_horizon[15].eligible_share_pct, 50.0)

    def test_empty_sample_does_not_invent_followup(self):
        summary = summarize_wallet_forward_exposure(
            [], observation_window_end_at=100, horizons_seconds=[900]
        )

        self.assertEqual(summary.buy_count, 0)
        self.assertIsNone(summary.median_remaining_observation_seconds)
        self.assertEqual(summary.horizons[0].eligible_buy_count, 0)
        self.assertEqual(summary.horizons[0].eligible_share_pct, 0.0)

    def test_event_after_run_end_is_rejected(self):
        with self.assertRaises(ValueError):
            summarize_wallet_forward_exposure(
                [_event(1, 101)],
                observation_window_end_at=100,
                horizons_seconds=[15],
            )

    def test_duplicate_event_is_rejected(self):
        event = _event(1, 90)
        with self.assertRaises(ValueError):
            summarize_wallet_forward_exposure(
                [event, event],
                observation_window_end_at=100,
                horizons_seconds=[15],
            )


if __name__ == "__main__":
    unittest.main()
