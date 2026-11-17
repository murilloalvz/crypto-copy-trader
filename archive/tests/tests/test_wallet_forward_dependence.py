import unittest

from src.wallet_forward_dependence import summarize_wallet_forward_dependence
from src.wallet_quote_drift import WalletQuoteDriftObservation
from src.wallet_quote_watch import ForwardBuyEvent


def _buy(event: int, wallet: str, token: str) -> ForwardBuyEvent:
    return ForwardBuyEvent(
        id=event,
        observation_key=f"e{event}",
        wallet_address=wallet,
        token_mint=token,
        chain_time=100 + event,
        observed_at=110 + event,
    )


def _drift(event: int, token: str, value: float, delay: int = 15) -> WalletQuoteDriftObservation:
    return WalletQuoteDriftObservation(
        source_event_key=f"e{event}",
        wallet_address="W",
        token_mint=token,
        side="buy",
        delay_seconds=delay,
        baseline_price_usd=1.0,
        delayed_price_usd=1.0 + value / 100.0,
        raw_price_change_pct=value,
        adverse_execution_drift_pct=value,
        target_request_lag_seconds=0,
        wallet_to_quote_seconds=delay,
        route_changed=None,
    )


class WalletForwardDependenceTests(unittest.TestCase):
    def test_repeated_wallet_token_buys_do_not_inflate_unique_units(self):
        buys = [
            _buy(1, "W", "A"),
            _buy(2, "W", "A"),
            _buy(3, "W", "A"),
            _buy(4, "W", "A"),
            _buy(5, "W", "B"),
            _buy(6, "W", "B"),
        ]
        summary = summarize_wallet_forward_dependence(buys)

        self.assertEqual(summary.buy_event_count, 6)
        self.assertEqual(summary.token_count, 2)
        self.assertEqual(summary.wallet_token_cluster_count, 2)
        self.assertEqual(summary.repeated_wallet_token_buy_count, 4)
        self.assertAlmostEqual(summary.repeated_wallet_token_buy_share_pct, 66.6666666667)
        self.assertIn("few_unique_tokens_for_event_level_inference", summary.cautions)
        self.assertIn("single_wallet_dominates_buy_events", summary.cautions)
        self.assertIn("repeated_same_wallet_token_actions", summary.cautions)

    def test_token_clustered_drift_equal_weights_tokens(self):
        buys = [
            _buy(1, "W", "A"),
            _buy(2, "W", "A"),
            _buy(3, "W", "A"),
            _buy(4, "W", "B"),
        ]
        drift = [
            _drift(1, "A", 100.0),
            _drift(2, "A", 100.0),
            _drift(3, "A", 100.0),
            _drift(4, "B", -100.0),
        ]

        summary = summarize_wallet_forward_dependence(buys, drift_observations=drift)
        item = summary.drift_clusters[0]

        self.assertEqual(item.event_count, 4)
        self.assertEqual(item.token_cluster_count, 2)
        self.assertEqual(item.event_median_adverse_drift_pct, 100.0)
        self.assertEqual(item.median_of_token_medians_pct, 0.0)
        self.assertEqual(item.min_token_median_pct, -100.0)
        self.assertEqual(item.max_token_median_pct, 100.0)

    def test_duplicate_event_key_is_rejected(self):
        buys = [_buy(1, "W", "A"), _buy(1, "W", "A")]
        with self.assertRaises(ValueError):
            summarize_wallet_forward_dependence(buys)


if __name__ == "__main__":
    unittest.main()
