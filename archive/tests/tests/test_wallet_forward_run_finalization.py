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
)


class WalletForwardRunFinalizationTests(unittest.TestCase):
    def test_completed_run_cannot_be_rewritten_as_aborted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "final.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_wallet_forward_run(
                    run_key="run",
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
                    "run", status="COMPLETED", ended_at=200, end_observation_id=0
                )
                with self.assertRaises(ValueError):
                    finish_wallet_forward_run(
                        "run", status="ABORTED", ended_at=300, end_observation_id=1
                    )
                loaded = get_wallet_forward_run("run")

        self.assertEqual(loaded.status, "COMPLETED")
        self.assertEqual(loaded.ended_at, 200)
        self.assertEqual(loaded.end_observation_id, 0)

    def test_aborted_run_cannot_be_rewritten_as_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "final.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_wallet_forward_run(
                    run_key="run",
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
                    "run", status="ABORTED", ended_at=200, end_observation_id=0
                )
                with self.assertRaises(ValueError):
                    finish_wallet_forward_run(
                        "run", status="COMPLETED", ended_at=300, end_observation_id=1
                    )
                loaded = get_wallet_forward_run("run")

        self.assertEqual(loaded.status, "ABORTED")
        self.assertEqual(loaded.ended_at, 200)
        self.assertEqual(loaded.end_observation_id, 0)


if __name__ == "__main__":
    unittest.main()
