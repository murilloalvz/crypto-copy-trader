import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_activity_discovery_run_v0 import (
    MARKET_ACTIVITY_DISCOVERY_ADMISSION_DURATION_SECONDS,
    assert_market_activity_discovery_admission_open_v0,
    close_market_activity_discovery_run_v0,
    create_market_activity_discovery_run_v0,
    interrupt_market_activity_discovery_run_v0,
)


class MarketActivityDiscoveryRunV0Tests(unittest.TestCase):
    def test_run_freezes_exact_six_hour_admission_window(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                run = create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1",
                    cohort_key="COHORT1",
                    started_at=100,
                )

        self.assertEqual(run.started_at, 100)
        self.assertEqual(
            run.admission_closes_at,
            100 + MARKET_ACTIVITY_DISCOVERY_ADMISSION_DURATION_SECONDS,
        )
        self.assertEqual(run.status, "OPEN")

    def test_exact_create_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=100
                )
                second = create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=100
                )

        self.assertEqual(first, second)

    def test_run_or_cohort_identity_cannot_be_reused_differently(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conflict.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=100
                )
                with self.assertRaises(ValueError):
                    create_market_activity_discovery_run_v0(
                        acquisition_run_key="RUN1", cohort_key="COHORT2", started_at=100
                    )
                with self.assertRaises(ValueError):
                    create_market_activity_discovery_run_v0(
                        acquisition_run_key="RUN2", cohort_key="COHORT1", started_at=100
                    )

    def test_normal_close_is_forbidden_before_frozen_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "close.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                run = create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=100
                )
                with self.assertRaises(ValueError):
                    close_market_activity_discovery_run_v0(
                        acquisition_run_key="RUN1",
                        observed_at=run.admission_closes_at - 1,
                    )
                closed = close_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1",
                    observed_at=run.admission_closes_at,
                )

        self.assertEqual(closed.status, "CLOSED")
        self.assertEqual(closed.closed_at, run.admission_closes_at)

    def test_admission_boundary_is_half_open(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "boundary.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                run = create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=100
                )
                assert_market_activity_discovery_admission_open_v0(run, considered_at=100)
                assert_market_activity_discovery_admission_open_v0(
                    run, considered_at=run.admission_closes_at - 1
                )
                with self.assertRaises(ValueError):
                    assert_market_activity_discovery_admission_open_v0(
                        run, considered_at=run.admission_closes_at
                    )

    def test_interruption_is_distinct_from_completed_run_and_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interrupt.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1", cohort_key="COHORT1", started_at=100
                )
                interrupted = interrupt_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1",
                    observed_at=200,
                    reason="collector_transport_failed",
                )
                replay = interrupt_market_activity_discovery_run_v0(
                    acquisition_run_key="RUN1",
                    observed_at=200,
                    reason="collector_transport_failed",
                )
                with self.assertRaises(ValueError):
                    close_market_activity_discovery_run_v0(
                        acquisition_run_key="RUN1",
                        observed_at=100 + MARKET_ACTIVITY_DISCOVERY_ADMISSION_DURATION_SECONDS,
                    )
                with self.assertRaises(ValueError):
                    interrupt_market_activity_discovery_run_v0(
                        acquisition_run_key="RUN1",
                        observed_at=201,
                        reason="different",
                    )

        self.assertEqual(interrupted, replay)
        self.assertEqual(interrupted.status, "INTERRUPTED")


if __name__ == "__main__":
    unittest.main()
