import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_activity_discovery_admission_v0 import (
    register_considered_market_activity_episode_v0,
)
from src.market_activity_discovery_audit_v0 import build_market_activity_discovery_audit_v0
from src.market_activity_discovery_run_v0 import create_market_activity_discovery_run_v0
from src.market_activity_discovery_scanner_v0 import scan_open_market_activity_discovery_run_v0
from src.market_opportunity_episode_store import assign_market_opportunity_trigger


class MarketActivityDiscoveryAuditV0Tests(unittest.TestCase):
    def _episode(self, *, trigger_key, mint, observed_at, chain_time):
        return assign_market_opportunity_trigger(
            acquisition_run_key="RUN1",
            trigger_key=trigger_key,
            token_mint=mint,
            trigger_kind="activity_acceleration",
            direction="upward_pressure",
            chain_time=chain_time,
            observed_at=observed_at,
            method_version="market_opportunity_radar_v1",
            venue="pump",
        )

    def test_audit_reconciles_denominator_lineage_and_pending_outcomes_without_economics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=1000
                )
                self._episode(trigger_key="TR1", mint="MINT_A", observed_at=1010, chain_time=1100)
                missing = self._episode(
                    trigger_key="TR2", mint="MINT_B", observed_at=1020, chain_time=1110
                )
                register_considered_market_activity_episode_v0(
                    acquisition_run_key="RUN1",
                    episode_key=missing.episode_key,
                    considered_at=missing.first_trigger_observed_at,
                )
                scan_open_market_activity_discovery_run_v0(acquisition_run_key="RUN1")
                audit = build_market_activity_discovery_audit_v0(acquisition_run_key="RUN1")

        self.assertEqual(audit.candidate_episode_count, 2)
        self.assertEqual(audit.cohort_denominator, 2)
        self.assertEqual(
            audit.disposition_counts,
            (("ANALYZABLE_T0", 1), ("T0_NOT_FROZEN", 1)),
        )
        self.assertEqual(audit.analyzable_t0_count, 1)
        self.assertEqual(audit.unregistered_candidate_episode_keys, ())
        self.assertEqual(audit.analyzable_missing_snapshot_lineage_episode_keys, ())
        self.assertEqual(audit.analyzable_missing_forward_horizons, ())
        self.assertEqual(audit.unexpected_outcome_episode_keys, ())
        self.assertEqual(
            [(item.horizon_seconds, item.status, item.count) for item in audit.outcome_status_counts],
            [(300, "PENDING", 1), (900, "PENDING", 1), (3600, "PENDING", 1)],
        )
        self.assertTrue(audit.integrity_ready_for_close_or_analysis)
        self.assertFalse(audit.economic_edge_evaluated)

    def test_unregistered_candidate_keeps_audit_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unregistered.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=1000
                )
                episode = self._episode(
                    trigger_key="TR1", mint="MINT_A", observed_at=1010, chain_time=1100
                )
                audit = build_market_activity_discovery_audit_v0(acquisition_run_key="RUN1")

        self.assertEqual(audit.unregistered_candidate_episode_keys, (episode.episode_key,))
        self.assertFalse(audit.integrity_ready_for_close_or_analysis)
        self.assertFalse(audit.economic_edge_evaluated)


if __name__ == "__main__":
    unittest.main()
