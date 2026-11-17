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
        near_miss = replace(valid, token="near", symbol="NEAR", dev_pct=11.0)
        report = build_wave_radar_report([valid, invalid, near_miss])

        summary = record_discovery_run(
            report,
            requested_token_limit=50,
            returned_count=3,
            policy=WaveRadarPolicy(),
            outcomes=(
                SignalPersistenceOutcome(valid.token, "created"),
                SignalPersistenceOutcome(invalid.token, "strategy_rejected"),
                SignalPersistenceOutcome(near_miss.token, "strategy_rejected"),
            ),
            started_at_ms=1_000,
            completed_at_ms=2_000,
        )

        run = rows("SELECT * FROM wave_discovery_runs")[0]
        self.assertEqual(summary.requested_limit, 50)
        self.assertEqual(run["returned_count"], 3)
        self.assertEqual(run["data_valid_count"], 2)
        self.assertEqual(run["strategy_candidate_count"], 1)
        self.assertEqual(run["signals_created_count"], 1)
        self.assertEqual(rejection_counts(summary.run_id)["pool_unavailable"], 1)
        self.assertEqual(
            rejection_counts(summary.run_id)["developer_concentration_high"],
            1,
        )

        rejections = rows(
            """SELECT token_mint, data_valid, selected_for_followup
            FROM wave_rejection_decisions ORDER BY token_mint"""
        )
        self.assertEqual(
            [item["token_mint"] for item in rejections],
            ["bad", "near"],
        )
        by_mint = {item["token_mint"]: item for item in rejections}
        self.assertEqual(by_mint["bad"]["data_valid"], 0)
        self.assertEqual(by_mint["bad"]["selected_for_followup"], 0)
        self.assertEqual(by_mint["near"]["data_valid"], 1)
        self.assertEqual(by_mint["near"]["selected_for_followup"], 1)

        followups = rows(
            """SELECT f.horizon_minutes
            FROM wave_rejection_followups f
            JOIN wave_rejection_decisions d ON d.id=f.rejection_id
            WHERE d.token_mint='near' ORDER BY f.horizon_minutes"""
        )
        self.assertEqual(
            [item["horizon_minutes"] for item in followups],
            [5, 15, 60],
        )


if __name__ == "__main__":
    unittest.main()
