import unittest
from dataclasses import replace
from datetime import datetime, timezone

from discover import format_report
from src.discovery.tracker_service import SolanaTrackerDiscoveryService
from tests.test_tracker_discovery_service import FakeTrackerClient, WALLET_GOOD


class DiscoveryCLITests(unittest.TestCase):
    def test_report_contains_counts_explanations_and_lab_wallet(self):
        report = SolanaTrackerDiscoveryService(
            client=FakeTrackerClient(),
            now=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
        ).discover(250)

        output = format_report(report, top_n=10)

        self.assertIn("Wallets analisadas: 2", output)
        self.assertIn("Passaram para o Candidate Score: 1", output)
        self.assertIn("Avaliadas por liquidez/copyability: 1", output)
        self.assertIn("Copyability Score:", output)
        self.assertIn("Capital em tokens líquidos:", output)
        self.assertIn("Candidate Score:", output)
        self.assertIn("Capital investido 30d:", output)
        self.assertIn("PnL, ROI, win rate, dias ativos e menor frequência", output)
        self.assertIn("Motivos:", output)
        self.assertIn("WALLET DE LABORATÓRIO SUGERIDA", output)
        self.assertIn(WALLET_GOOD, output)
        self.assertIn("Copyability Score mede viabilidade técnica estimada", output)

    def test_report_keeps_liquidity_near_miss_in_observation_watchlist(self):
        client = FakeTrackerClient()
        original_positions = client.wallet_positions

        def illiquid_capital(address, *, period, limit):
            result = original_positions(address, period=period, limit=limit)
            positions = tuple(
                replace(
                    item,
                    liquidity_usd=100_000 if index < 6 else 10_000,
                    invested_usd=100 if index < 6 else 250,
                )
                for index, item in enumerate(result.positions)
            )
            return replace(result, positions=positions)

        client.wallet_positions = illiquid_capital
        report = SolanaTrackerDiscoveryService(
            client=client,
            now=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
        ).discover(250)

        output = format_report(report, top_n=10)

        self.assertEqual(report.copyable_count, 0)
        self.assertEqual(report.observed_count, 1)
        self.assertIn("Wallets somente para observação: 1", output)
        self.assertIn("Copyability Score:", output)
        self.assertIn("| OBSERVAÇÃO", output)
        self.assertIn("WATCHLIST DE OBSERVAÇÃO", output)
        self.assertIn(WALLET_GOOD, output)


if __name__ == "__main__":
    unittest.main()
