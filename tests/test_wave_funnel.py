import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.database import initialize_database, rows
from src.wave_funnel import record_discovery_run, rejection_counts
from src.wave_paper import SignalPersistenceOutcome
from src.wave_radar import WaveRadarPolicy, build_wave_radar_report
from tests.test_wave_radar import token


class WaveFunnelTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.patch = patch.object(
            database,
            "settings",
            SimpleNamespace(database_path=Path(self.directory.name) / "funnel.db"),
        )
        self.patch.start()
        initialize_database()

    def tearDown(self):
        self.patch.stop()
        self.directory.cleanup()

    def test_records_source_limit_filters_candidates_and_persistence(self):
        valid = token()
        invalid = replace(valid, token="bad", pool_address=None)
        report = build_wave_radar_report([valid, invalid])

        summary = record_discovery_run(
            report,
            requested_token_limit=50,
            returned_count=2,
            policy=WaveRadarPolicy(),
            outcomes=(
                SignalPersistenceOutcome(valid.token, "created"),
                SignalPersistenceOutcome(invalid.token, "strategy_rejected"),
            ),
            started_at_ms=1_000,
            completed_at_ms=2_000,
        )

        run = rows("SELECT * FROM wave_discovery_runs")[0]
        self.assertEqual(summary.requested_limit, 50)
        self.assertEqual(run["returned_count"], 2)
        self.assertEqual(run["data_valid_count"], 1)
        self.assertEqual(run["strategy_candidate_count"], 1)
        self.assertEqual(run["signals_created_count"], 1)
        self.assertEqual(rejection_counts(summary.run_id)["pool_unavailable"], 1)


if __name__ == "__main__":
    unittest.main()
