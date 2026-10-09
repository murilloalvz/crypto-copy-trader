import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import wallet_forward_run_admin as admin
from src import database
from src.wallet_forward_runs import create_wallet_forward_run, get_wallet_forward_run


class WalletForwardRunAdminTests(unittest.TestCase):
    def test_abort_requires_exact_key_and_stopped_process_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "admin.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_wallet_forward_run(
                    run_key="active",
                    started_at=100,
                    baseline_observation_id=0,
                    cohort=["A"],
                    interval_seconds=30,
                    quote_delays_seconds=[],
                    with_jupiter_quotes=False,
                    copy_size_usd=25.0,
                    quote_mode="none",
                )
                self.assertEqual(
                    admin._abort_stale("active", "wrong", True),
                    2,
                )
                self.assertEqual(
                    admin._abort_stale("active", "active", False),
                    2,
                )
                loaded = get_wallet_forward_run("active")

        self.assertEqual(loaded.status, "ACTIVE")

    def test_confirmed_stale_abort_preserves_manifest_as_aborted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "admin.db"
            with (
                patch.object(database, "settings", SimpleNamespace(database_path=path)),
                patch.object(admin, "latest_forward_observation_id", return_value=3),
                patch.object(admin.time, "time", return_value=200),
            ):
                create_wallet_forward_run(
                    run_key="active",
                    started_at=100,
                    baseline_observation_id=2,
                    cohort=["A"],
                    interval_seconds=30,
                    quote_delays_seconds=[],
                    with_jupiter_quotes=False,
                    copy_size_usd=25.0,
                    quote_mode="none",
                )
                code = admin._abort_stale("active", "active", True)
                loaded = get_wallet_forward_run("active")

        self.assertEqual(code, 0)
        self.assertEqual(loaded.status, "ABORTED")
        self.assertEqual(loaded.ended_at, 200)
        self.assertEqual(loaded.end_observation_id, 3)


if __name__ == "__main__":
    unittest.main()
