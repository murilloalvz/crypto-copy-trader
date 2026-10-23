import unittest

from src.discovery.models import LeaderboardWallet
from src.discovery.ranking import CandidatePolicy
from src.discovery.service import WalletDiscoveryService
from tests.test_discovery_ranking import period


class FakeBirdeyeClient:
    def __init__(self):
        self.calls = []
        self.wallets = [
            LeaderboardWallet("good", 20_000, 100_000, 100),
            LeaderboardWallet("few", 10_000, 50_000, 5),
            LeaderboardWallet("weak", 500_000, 900_000, 50),
        ]

    def trader_leaderboard(self, limit, *, period, sort_by):
        self.calls.append(("leaderboard", limit, period, sort_by))
        return self.wallets[:limit]

    def wallet_pnl(self, address, duration):
        self.calls.append((address, duration))
        if address == "weak":
            return period("30d", trades=50, wins=2, losses=8, tokens=1, pnl=500_000, roi=200)
        if duration == "7d":
            return period("7d", trades=12, pnl=2_000, roi=8)
        if duration == "90d":
            return period("90d", trades=250, pnl=60_000, roi=45)
        return period("30d", trades=100, pnl=20_000, roi=30)


class DiscoveryServiceTests(unittest.TestCase):
    def test_expensive_periods_are_only_fetched_after_cheap_filters(self):
        client = FakeBirdeyeClient()

        report = WalletDiscoveryService(client, CandidatePolicy()).discover(3)

        self.assertEqual(report.source_count, 3)
        self.assertEqual(report.prefiltered_count, 2)
        self.assertEqual(report.enriched_30d_count, 1)
        self.assertEqual(report.passed_count, 1)
        self.assertEqual(report.candidates[0].address, "good")
        self.assertNotIn(("few", "30d"), client.calls)
        self.assertNotIn(("weak", "7d"), client.calls)
        self.assertIn("source_too_few_trades", report.rejected_by_reason)
        self.assertIn("win_rate_below_minimum", report.rejected_by_reason)


if __name__ == "__main__":
    unittest.main()
