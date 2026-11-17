import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.opportunity_provider_attempt_store import (
    begin_provider_attempt,
    complete_provider_attempt,
    list_provider_attempts,
    load_provider_attempt,
)


class OpportunityProviderAttemptStoreTests(unittest.TestCase):
    def test_begin_is_idempotent_and_completion_is_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempts.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self.assertTrue(
                    begin_provider_attempt(
                        attempt_key="attempt-1",
                        acquisition_run_key="run",
                        episode_key="episode",
                        provider="jupiter",
                        purpose="entry",
                        started_at=100,
                    )
                )
                self.assertFalse(
                    begin_provider_attempt(
                        attempt_key="attempt-1",
                        acquisition_run_key="run",
                        episode_key="episode",
                        provider="jupiter",
                        purpose="entry",
                        started_at=101,
                    )
                )
                started = load_provider_attempt(attempt_key="attempt-1")
                self.assertEqual(started.status, "STARTED")

                completed = complete_provider_attempt(
                    attempt_key="attempt-1",
                    status="AVAILABLE",
                    completed_at=110,
                    artifact_key="quote-1",
                    details={"router": "metis"},
                )
                self.assertEqual(completed.status, "AVAILABLE")
                self.assertEqual(completed.artifact_key, "quote-1")

                replay = complete_provider_attempt(
                    attempt_key="attempt-1",
                    status="AVAILABLE",
                    completed_at=110,
                    artifact_key="quote-1",
                    details={"router": "metis"},
                )
                self.assertEqual(replay, completed)
                with self.assertRaises(ValueError):
                    complete_provider_attempt(
                        attempt_key="attempt-1",
                        status="UNAVAILABLE",
                        completed_at=111,
                    )

    def test_conflicting_attempt_identity_and_backdating_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempts.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                begin_provider_attempt(
                    attempt_key="attempt-1",
                    acquisition_run_key="run",
                    episode_key="episode",
                    provider="jupiter",
                    purpose="entry",
                    started_at=100,
                )
                with self.assertRaises(ValueError):
                    begin_provider_attempt(
                        attempt_key="attempt-2",
                        acquisition_run_key="run",
                        episode_key="episode",
                        provider="jupiter",
                        purpose="entry",
                        started_at=101,
                    )
                with self.assertRaises(ValueError):
                    begin_provider_attempt(
                        attempt_key="attempt-1",
                        acquisition_run_key="run",
                        episode_key="episode",
                        provider="jupiter",
                        purpose="entry",
                        started_at=99,
                    )
                with self.assertRaises(ValueError):
                    complete_provider_attempt(
                        attempt_key="attempt-1",
                        status="PROVIDER_ERROR",
                        completed_at=99,
                    )

    def test_list_keeps_started_crash_state_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempts.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                begin_provider_attempt(
                    attempt_key="attempt-1",
                    acquisition_run_key="run",
                    episode_key="episode-1",
                    provider="jupiter",
                    purpose="entry",
                    started_at=100,
                )
                begin_provider_attempt(
                    attempt_key="attempt-2",
                    acquisition_run_key="run",
                    episode_key="episode-2",
                    provider="risk",
                    purpose="hazard",
                    started_at=101,
                )
                rows = list_provider_attempts(
                    acquisition_run_key="run",
                    provider="jupiter",
                    purpose="entry",
                )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "STARTED")


if __name__ == "__main__":
    unittest.main()
