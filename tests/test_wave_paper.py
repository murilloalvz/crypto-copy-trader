import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.database import initialize_database, rows
from src.wave_paper import (
    latest_paper_signals,
    record_paper_signals,
    update_due_paper_checks,
)
from src.wave_radar import build_wave_radar_report
from tests.test_wave_radar import token


class FakePriceProvider:
    def __init__(self, price):
        self.price = price
        self.timestamps = []

    def price_at(self, _token, timestamp, *, max_distance_seconds=3_600):
        self.timestamps.append(timestamp)
        self.max_distance_seconds = max_distance_seconds
        return self.price


class WavePaperTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "wave-paper.db"
        self.settings_patch = patch.object(
            database, "settings", SimpleNamespace(database_path=self.path)
        )
        self.settings_patch.start()
        initialize_database()

    def tearDown(self):
        self.settings_patch.stop()
        self.directory.cleanup()

    def approved_results(self):
        return build_wave_radar_report([token()]).results

    def test_records_one_signal_with_three_horizons_and_cooldown(self):
        created = record_paper_signals(
            self.approved_results(),
            detected_at=1_000,
            copy_size_usd=25,
            slippage_bps=100,
        )
        duplicate = record_paper_signals(
            self.approved_results(),
            detected_at=1_300,
            copy_size_usd=25,
            slippage_bps=100,
        )

        self.assertEqual(created, 1)
        self.assertEqual(duplicate, 0)
        self.assertEqual(rows("SELECT COUNT(*) AS total FROM wave_signals")[0]["total"], 1)
        self.assertEqual(
            rows("SELECT COUNT(*) AS total FROM wave_signal_checks")[0]["total"], 3
        )

    def test_prices_exact_due_horizons_and_completes_signal(self):
        record_paper_signals(
            self.approved_results(),
            detected_at=1_000,
            copy_size_usd=25,
            slippage_bps=100,
        )
        provider = FakePriceProvider(0.0011)

        first = update_due_paper_checks(provider, now=1_301)
        final = update_due_paper_checks(provider, now=4_601)
        signal = latest_paper_signals(1)[0]

        self.assertEqual(first, {"completed": 1, "failed": 0, "pending": 2})
        self.assertEqual(final, {"completed": 2, "failed": 0, "pending": 0})
        self.assertEqual(provider.timestamps, [1_300, 1_900, 4_600])
        self.assertEqual(provider.max_distance_seconds, 120)
        self.assertEqual(signal["status"], "completed")
        self.assertAlmostEqual(signal["checks"][0]["return_pct"], 7.821782, places=5)
        self.assertAlmostEqual(signal["checks"][0]["pnl_usd"], 1.955445, places=5)


if __name__ == "__main__":
    unittest.main()
