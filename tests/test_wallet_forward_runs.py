import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.database import connection
from src.wallet_forward_runs import (
    CURRENT_RUNTIME_VERSION,
    LEGACY_RUNTIME_VERSION,
    create_wallet_forward_run,
    finish_wallet_forward_run,
    get_wallet_forward_run,
    latest_wallet_forward_run,
    list_wallet_forward_runs,
)


class WalletForwardRunTests(unittest.TestCase):
    def test_run_lifecycle_persists_frozen_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                created = create_wallet_forward_run(
                    run_key="run-1",
                    started_at=1000,
                    baseline_observation_id=12,
                    cohort=["A", "B", "A"],
                    interval_seconds=30,
                    quote_delays_seconds=[0, 15, 30, 60, 120],
                    with_jupiter_quotes=True,
                    copy_size_usd=25.0,
                    quote_mode="proxy",
                    quote_intake_grace_seconds=35,
                )
                finished = finish_wallet_forward_run(
                    "run-1",
                    status="COMPLETED",
                    ended_at=1300,
                    end_observation_id=18,
                )
                loaded = get_wallet_forward_run("run-1")
                latest = latest_wallet_forward_run(completed_only=True)

        self.assertEqual(created.status, "ACTIVE")
        self.assertEqual(created.cohort, ("A", "B"))
        self.assertEqual(created.baseline_observation_id, 12)
        self.assertEqual(created.quote_delays_seconds, (0, 15, 30, 60, 120))
        self.assertEqual(created.runtime_version, CURRENT_RUNTIME_VERSION)
        self.assertEqual(created.quote_intake_grace_seconds, 35)
        self.assertEqual(finished.status, "COMPLETED")
        self.assertEqual(finished.end_observation_id, 18)
        self.assertEqual(loaded, finished)
        self.assertEqual(latest, finished)

    def test_aborted_run_is_latest_but_not_latest_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_wallet_forward_run(
                    run_key="completed",
                    started_at=100,
                    baseline_observation_id=0,
                    cohort=["A"],
                    interval_seconds=30,
                    quote_delays_seconds=[],
                    with_jupiter_quotes=False,
                    copy_size_usd=25.0,
                    quote_mode="none",
                )
                finish_wallet_forward_run(
                    "completed", status="COMPLETED", ended_at=200, end_observation_id=1
                )
                create_wallet_forward_run(
                    run_key="aborted",
                    started_at=300,
                    baseline_observation_id=1,
                    cohort=["A"],
                    interval_seconds=30,
                    quote_delays_seconds=[0],
                    with_jupiter_quotes=True,
                    copy_size_usd=25.0,
                    quote_mode="proxy",
                )
                finish_wallet_forward_run(
                    "aborted", status="ABORTED", ended_at=350, end_observation_id=2
                )

                latest_any = latest_wallet_forward_run()
                latest_completed = latest_wallet_forward_run(completed_only=True)

        self.assertEqual(latest_any.run_key, "aborted")
        self.assertEqual(latest_completed.run_key, "completed")

    def test_list_runs_is_newest_first_and_can_filter_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "list-runs.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_wallet_forward_run(
                    run_key="old-completed",
                    started_at=100,
                    baseline_observation_id=0,
                    cohort=["A"],
                    interval_seconds=30,
                    quote_delays_seconds=[],
                    with_jupiter_quotes=False,
                    copy_size_usd=25.0,
                    quote_mode="none",
                )
                finish_wallet_forward_run(
                    "old-completed", status="COMPLETED", ended_at=150, end_observation_id=0
                )
                create_wallet_forward_run(
                    run_key="middle-aborted",
                    started_at=200,
                    baseline_observation_id=0,
                    cohort=["A"],
                    interval_seconds=30,
                    quote_delays_seconds=[],
                    with_jupiter_quotes=False,
                    copy_size_usd=25.0,
                    quote_mode="none",
                )
                finish_wallet_forward_run(
                    "middle-aborted", status="ABORTED", ended_at=250, end_observation_id=0
                )
                create_wallet_forward_run(
                    run_key="new-completed",
                    started_at=300,
                    baseline_observation_id=0,
                    cohort=["A"],
                    interval_seconds=30,
                    quote_delays_seconds=[],
                    with_jupiter_quotes=False,
                    copy_size_usd=25.0,
                    quote_mode="none",
                )
                finish_wallet_forward_run(
                    "new-completed", status="COMPLETED", ended_at=350, end_observation_id=0
                )

                all_runs = list_wallet_forward_runs(limit=10)
                completed = list_wallet_forward_runs(status="COMPLETED", limit=10)
                latest_two = list_wallet_forward_runs(limit=2)

        self.assertEqual(
            [item.run_key for item in all_runs],
            ["new-completed", "middle-aborted", "old-completed"],
        )
        self.assertEqual(
            [item.run_key for item in completed],
            ["new-completed", "old-completed"],
        )
        self.assertEqual(
            [item.run_key for item in latest_two],
            ["new-completed", "middle-aborted"],
        )

    def test_invalid_quote_mode_combinations_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with self.assertRaises(ValueError):
                    create_wallet_forward_run(
                        run_key="bad-1",
                        started_at=1,
                        baseline_observation_id=0,
                        cohort=["A"],
                        interval_seconds=30,
                        quote_delays_seconds=[0],
                        with_jupiter_quotes=True,
                        copy_size_usd=25.0,
                        quote_mode="none",
                    )
                with self.assertRaises(ValueError):
                    create_wallet_forward_run(
                        run_key="bad-2",
                        started_at=1,
                        baseline_observation_id=0,
                        cohort=["A"],
                        interval_seconds=30,
                        quote_delays_seconds=[],
                        with_jupiter_quotes=False,
                        copy_size_usd=25.0,
                        quote_mode="proxy",
                    )

    def test_finish_cannot_move_observation_cursor_backward(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_wallet_forward_run(
                    run_key="run",
                    started_at=10,
                    baseline_observation_id=5,
                    cohort=["A"],
                    interval_seconds=30,
                    quote_delays_seconds=[],
                    with_jupiter_quotes=False,
                    copy_size_usd=25.0,
                    quote_mode="none",
                )
                with self.assertRaises(ValueError):
                    finish_wallet_forward_run(
                        "run", status="COMPLETED", ended_at=20, end_observation_id=4
                    )

    def test_old_manifest_schema_migrates_to_explicit_legacy_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-runs.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with connection() as conn:
                    conn.executescript(
                        """
                        CREATE TABLE wallet_forward_runs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            run_key TEXT NOT NULL UNIQUE,
                            started_at INTEGER NOT NULL,
                            ended_at INTEGER,
                            baseline_observation_id INTEGER NOT NULL,
                            end_observation_id INTEGER,
                            cohort_json TEXT NOT NULL,
                            interval_seconds INTEGER NOT NULL,
                            quote_delays_json TEXT NOT NULL,
                            with_jupiter_quotes INTEGER NOT NULL,
                            copy_size_usd REAL NOT NULL,
                            quote_mode TEXT NOT NULL,
                            status TEXT NOT NULL,
                            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                        );
                        INSERT INTO wallet_forward_runs(
                            run_key, started_at, ended_at, baseline_observation_id,
                            end_observation_id, cohort_json, interval_seconds,
                            quote_delays_json, with_jupiter_quotes, copy_size_usd,
                            quote_mode, status
                        ) VALUES (
                            'legacy', 100, 200, 0, 1, '["A"]', 30,
                            '[0,15,30,60,120]', 1, 25.0, 'proxy', 'COMPLETED'
                        );
                        """
                    )

                loaded = get_wallet_forward_run("legacy")

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.runtime_version, LEGACY_RUNTIME_VERSION)
        self.assertEqual(loaded.quote_intake_grace_seconds, 0)


if __name__ == "__main__":
    unittest.main()
