import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_activity_discovery_admission_v0 import (
    register_considered_market_activity_episode_v0,
)
from src.market_activity_discovery_run_v0 import (
    close_market_activity_discovery_run_v0,
    create_market_activity_discovery_run_v0,
)
from src.market_activity_discovery_scanner_v0 import (
    load_market_activity_discovery_candidate_episodes_v0,
    scan_open_market_activity_discovery_run_v0,
)
from src.market_opportunity_episode_store import assign_market_opportunity_trigger


class MarketActivityDiscoveryScannerV0Tests(unittest.TestCase):
    def _episode(self, *, run_key="RUN1", trigger_key, mint, observed_at, chain_time):
        return assign_market_opportunity_trigger(
            acquisition_run_key=run_key,
            trigger_key=trigger_key,
            token_mint=mint,
            trigger_kind="activity_acceleration",
            direction="upward_pressure",
            chain_time=chain_time,
            observed_at=observed_at,
            method_version="market_opportunity_radar_v1",
            venue="pump",
        )

    def test_scan_processes_unregistered_skips_immutable_missing_and_excludes_close_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scanner.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                run = create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=1000
                )
                first = self._episode(
                    trigger_key="TR1", mint="MINT_A", observed_at=1010, chain_time=1100
                )
                missing = self._episode(
                    trigger_key="TR2", mint="MINT_B", observed_at=1020, chain_time=1110
                )
                self._episode(
                    trigger_key="TR3",
                    mint="MINT_C",
                    observed_at=run.admission_closes_at,
                    chain_time=99999,
                )
                register_considered_market_activity_episode_v0(
                    acquisition_run_key="RUN1",
                    episode_key=missing.episode_key,
                    considered_at=missing.first_trigger_observed_at,
                )

                candidates = load_market_activity_discovery_candidate_episodes_v0(run)
                first_scan = scan_open_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1"
                )
                replay = scan_open_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1"
                )

        self.assertEqual([item.episode_key for item in candidates], [first.episode_key, missing.episode_key])
        self.assertEqual(first_scan.candidate_episode_count, 2)
        self.assertEqual(first_scan.newly_processed_count, 1)
        self.assertEqual(first_scan.already_registered_count, 1)
        self.assertEqual(
            [(item.action, item.disposition) for item in first_scan.entries],
            [
                ("PROCESSED_ANALYZABLE_T0", "ANALYZABLE_T0"),
                ("ALREADY_REGISTERED_IMMUTABLE", "T0_NOT_FROZEN"),
            ],
        )
        self.assertEqual(replay.newly_processed_count, 0)
        self.assertEqual(replay.already_registered_count, 2)
        self.assertEqual(replay.provider_calls_performed, 0)
        self.assertFalse(replay.economic_edge_evaluated)

    def test_closed_run_cannot_backfill_unregistered_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "closed.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                run = create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=1000
                )
                self._episode(
                    trigger_key="TR1", mint="MINT_A", observed_at=1010, chain_time=1100
                )
                close_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1",
                    observed_at=run.admission_closes_at,
                )
                with self.assertRaises(ValueError):
                    scan_open_market_activity_discovery_run_v0(acquisition_run_key="RUN1")


if __name__ == "__main__":
    unittest.main()
