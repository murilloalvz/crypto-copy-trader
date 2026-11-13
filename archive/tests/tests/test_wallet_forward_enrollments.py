import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.database import connection
from src.wallet_forward_enrollments import (
    freeze_wallet_forward_enrollment,
    load_wallet_forward_enrollments,
)
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema
from src.wallet_forward_runs import (
    create_wallet_forward_run,
    finish_wallet_forward_run,
    get_wallet_forward_run,
)


class WalletForwardEnrollmentTests(unittest.TestCase):
    def _insert_observation(
        self,
        *,
        observation_key: str,
        run_key: str,
        side: str,
        observed_at: int,
    ) -> int:
        ensure_wallet_forward_observation_schema()
        with connection() as conn:
            cursor = conn.execute(
                """INSERT INTO wallet_forward_observations(
                    observation_key, wallet_address, token_mint, side,
                    chain_time, observed_at, source, run_key
                ) VALUES (?, 'wallet-A', 'token-X', ?, ?, ?, 'test', ?)""",
                (observation_key, side, observed_at - 1, observed_at, run_key),
            )
            return int(cursor.lastrowid)

    def test_freeze_enrolls_only_buys_at_or_before_cutoff_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "enrollment.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_wallet_forward_run(
                    run_key="run-1",
                    started_at=100,
                    baseline_observation_id=0,
                    cohort=["wallet-A"],
                    interval_seconds=10,
                    quote_delays_seconds=[0, 15],
                    with_jupiter_quotes=True,
                    copy_size_usd=25.0,
                    quote_mode="proxy",
                    enrollment_ends_at=200,
                    follow_up_ends_at=300,
                )
                buy_1 = self._insert_observation(
                    observation_key="buy-1",
                    run_key="run-1",
                    side="buy",
                    observed_at=150,
                )
                self._insert_observation(
                    observation_key="sell-1",
                    run_key="run-1",
                    side="sell",
                    observed_at=170,
                )
                buy_2 = self._insert_observation(
                    observation_key="buy-2",
                    run_key="run-1",
                    side="buy",
                    observed_at=210,
                )

                enrolled = freeze_wallet_forward_enrollment(
                    "run-1", cutoff_observation_id=buy_1 + 1
                )
                enrolled_again = freeze_wallet_forward_enrollment(
                    "run-1", cutoff_observation_id=buy_1 + 1
                )
                loaded_run = get_wallet_forward_run("run-1")

        self.assertEqual([item.observation_key for item in enrolled], ["buy-1"])
        self.assertEqual(enrolled_again, enrolled)
        self.assertEqual(loaded_run.enrollment_cutoff_observation_id, buy_1 + 1)
        self.assertGreater(buy_2, loaded_run.enrollment_cutoff_observation_id)

    def test_divergent_second_cutoff_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "divergent.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_wallet_forward_run(
                    run_key="run-2",
                    started_at=100,
                    baseline_observation_id=0,
                    cohort=["wallet-A"],
                    interval_seconds=10,
                    quote_delays_seconds=[],
                    with_jupiter_quotes=False,
                    copy_size_usd=25.0,
                    quote_mode="none",
                    enrollment_ends_at=200,
                    follow_up_ends_at=300,
                )
                buy_id = self._insert_observation(
                    observation_key="buy-1",
                    run_key="run-2",
                    side="buy",
                    observed_at=150,
                )
                freeze_wallet_forward_enrollment("run-2", cutoff_observation_id=buy_id)
                with self.assertRaises(ValueError):
                    freeze_wallet_forward_enrollment(
                        "run-2", cutoff_observation_id=buy_id + 1
                    )

    def test_completed_enrollment_run_requires_frozen_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "completed.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_wallet_forward_run(
                    run_key="run-3",
                    started_at=100,
                    baseline_observation_id=0,
                    cohort=["wallet-A"],
                    interval_seconds=10,
                    quote_delays_seconds=[],
                    with_jupiter_quotes=False,
                    copy_size_usd=25.0,
                    quote_mode="none",
                    enrollment_ends_at=200,
                    follow_up_ends_at=300,
                )
                with self.assertRaises(ValueError):
                    finish_wallet_forward_run(
                        "run-3",
                        status="COMPLETED",
                        ended_at=300,
                        end_observation_id=0,
                    )

    def test_legacy_run_has_no_silent_enrollment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                create_wallet_forward_run(
                    run_key="legacy",
                    started_at=100,
                    baseline_observation_id=0,
                    cohort=["wallet-A"],
                    interval_seconds=10,
                    quote_delays_seconds=[],
                    with_jupiter_quotes=False,
                    copy_size_usd=25.0,
                    quote_mode="none",
                )
                with self.assertRaises(ValueError):
                    freeze_wallet_forward_enrollment(
                        "legacy", cutoff_observation_id=0
                    )
                self.assertEqual(load_wallet_forward_enrollments("legacy"), ())


if __name__ == "__main__":
    unittest.main()
