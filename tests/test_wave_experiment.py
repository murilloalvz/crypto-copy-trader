import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.database import initialize_database
from src.wave_metrics import build_wave_evaluation_report
from src.wave_paper import (
    WAVE_STRATEGY_VERSION,
    record_paper_signals,
    update_due_paper_checks,
)
from src.wave_radar import build_wave_radar_report
from tests.test_wave_radar import token


class FixedPriceProvider:
    def __init__(self, price: float):
        self.price = price

    def price_at(self, _token, _timestamp, *, max_distance_seconds=3_600):
        return self.price


class WaveExperimentIntegrationTests(unittest.TestCase):
    def test_radar_to_paper_to_robustness_report_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "experiment.db"
            with patch.object(
                database, "settings", SimpleNamespace(database_path=path)
            ):
                initialize_database()
                second_token = replace(
                    token(symbol="WAVE2"),
                    token="HkFGQsW8mr8DTC2AE2WcC7MzwSnynfEryGMQSht271nf",
                )
                radar_report = build_wave_radar_report([token(), second_token])

                created = record_paper_signals(
                    radar_report.results,
                    detected_at=1_000,
                    copy_size_usd=25,
                    slippage_bps=100,
                )
                updated = update_due_paper_checks(
                    FixedPriceProvider(0.0011),
                    now=4_601,
                    max_attempts=1,
                )
                evaluation = build_wave_evaluation_report(WAVE_STRATEGY_VERSION)

        self.assertEqual(created, 2)
        self.assertEqual(updated, {"completed": 6, "failed": 0, "pending": 0})
        self.assertEqual(evaluation.signal_count, 2)
        self.assertEqual([item.sample_size for item in evaluation.horizons], [2, 2, 2])
        self.assertEqual(len(evaluation.slippage_stress), 12)
        self.assertEqual(len(evaluation.cohorts), 6)
        self.assertTrue(
            all(item.average_return_pct > 0 for item in evaluation.horizons)
        )


if __name__ == "__main__":
    unittest.main()
