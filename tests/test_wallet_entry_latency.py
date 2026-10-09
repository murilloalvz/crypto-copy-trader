import unittest

from src.wallet_entry_latency import summarize_wallet_entry_latency
from src.wallet_quote_drift import WalletQuotePathPoint


def _point(event: str, *, delay: int, chain: int, observed: int, quote: int) -> WalletQuotePathPoint:
    return WalletQuotePathPoint(
        source_event_key=event,
        wallet_address="W",
        token_mint="T",
        side="buy",
        wallet_chain_time=chain,
        wallet_observed_at=observed,
        delay_seconds=delay,
        target_at=observed + delay,
        requested_at=observed + delay,
        completed_at=quote,
        quote_observed_at=quote,
        price_usd=1.0,
        executable=False,
        source="test",
        route_id=None,
    )


class WalletEntryLatencyTests(unittest.TestCase):
    def test_delay_is_after_detection_not_after_chain_time(self):
        points = [
            _point("a", delay=0, chain=100, observed=135, quote=140),
            _point("a", delay=15, chain=100, observed=135, quote=155),
            _point("b", delay=0, chain=200, observed=240, quote=246),
            _point("b", delay=15, chain=200, observed=240, quote=261),
        ]

        summary = summarize_wallet_entry_latency(points, buy_event_count=2)
        by_delay = {item.delay_seconds: item for item in summary.delays}

        self.assertEqual(by_delay[0].median_chain_to_detection_seconds, 37.5)
        self.assertEqual(by_delay[0].median_detection_to_quote_seconds, 5.5)
        self.assertEqual(by_delay[0].median_chain_to_quote_seconds, 43.0)
        self.assertEqual(by_delay[0].within_30s_share_pct, 0.0)
        self.assertEqual(by_delay[0].within_60s_share_pct, 100.0)
        self.assertEqual(by_delay[15].median_chain_to_quote_seconds, 58.0)

    def test_quote_coverage_keeps_missing_buy_in_denominator(self):
        points = [_point("a", delay=0, chain=100, observed=110, quote=111)]
        summary = summarize_wallet_entry_latency(points, buy_event_count=2)

        self.assertEqual(summary.delays[0].quoted_event_count, 1)
        self.assertEqual(summary.delays[0].coverage_pct, 50.0)

    def test_duplicate_event_delay_uses_earliest_quote_once(self):
        points = [
            _point("a", delay=0, chain=100, observed=110, quote=120),
            _point("a", delay=0, chain=100, observed=110, quote=115),
        ]
        summary = summarize_wallet_entry_latency(points, buy_event_count=1)

        self.assertEqual(summary.delays[0].quoted_event_count, 1)
        self.assertEqual(summary.delays[0].median_chain_to_quote_seconds, 15.0)


if __name__ == "__main__":
    unittest.main()
