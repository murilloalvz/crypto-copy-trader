import unittest
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
        self.assertIn("Passaram para o ranking: 1", output)
        self.assertIn("Candidate Score:", output)
        self.assertIn("Motivos:", output)
        self.assertIn("WALLET DE LABORATÓRIO SUGERIDA", output)
        self.assertIn(WALLET_GOOD, output)
        self.assertIn("não mede copyability completa", output)


if __name__ == "__main__":
    unittest.main()
