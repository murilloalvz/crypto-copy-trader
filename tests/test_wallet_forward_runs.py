import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.wallet_forward_runs import (
    create_wallet_forward_run,
    finish_wallet_forward_run,
    get_wallet_forward_run,
    latest_wallet_forward_run,
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


if __name__ == "__main__":
    unittest.main()
