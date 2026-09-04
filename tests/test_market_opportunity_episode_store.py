import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

from src import database
from src.market_opportunity_episode_store import (
    _run_with_sqlite_lock_retry,
    assign_market_opportunity_trigger,
    count_market_trigger_replay_conflicts,
    freeze_market_opportunity_decision_as_of,
    load_market_opportunity_episode_triggers,
)


class MarketOpportunityEpisodeStoreTests(unittest.TestCase):
    def _assign(
        self,
        *,
        run="run-a",
        key="t1",
        token="T",
        observed=100,
        chain=95,
        direction="upward_pressure",
        kind="activity_acceleration",
    ):
        return assign_market_opportunity_trigger(
            acquisition_run_key=run,
            trigger_key=key,
            token_mint=token,
            trigger_kind=kind,
            direction=direction,
            chain_time=chain,
            observed_at=observed,
            method_version="market_opportunity_radar_v1",
            venue="pump",
        )

    def test_same_token_within_60_seconds_shares_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = self._assign(key="t1", observed=100, chain=95)
                second = self._assign(key="t2", observed=159, chain=154)
                triggers = load_market_opportunity_episode_triggers(first.episode_key)
        self.assertEqual(first.episode_key, second.episode_key)
        self.assertEqual(len(triggers), 2)

    def test_trigger_exactly_at_close_opens_new_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = self._assign(key="t1", observed=100, chain=95)
                second = self._assign(key="t2", observed=160, chain=155)
        self.assertNotEqual(first.episode_key, second.episode_key)

    def test_different_acquisition_runs_never_share_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = self._assign(run="run-a", key="t1", observed=100, chain=95)
                second = self._assign(run="run-b", key="t2", observed=110, chain=105)
        self.assertNotEqual(first.episode_key, second.episode_key)

    def test_market_trigger_requires_no_tracked_wallet(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._assign()
                trigger = load_market_opportunity_episode_triggers(episode.episode_key)[0]
        self.assertEqual(trigger.token_mint, "T")
        self.assertFalse(hasattr(trigger, "wallet_address"))

    def test_decision_as_of_is_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._assign()
                frozen = freeze_market_opportunity_decision_as_of(
                    episode.episode_key, decision_as_of=130
                )
                same = freeze_market_opportunity_decision_as_of(
                    episode.episode_key, decision_as_of=130
                )
                with self.assertRaises(ValueError):
                    freeze_market_opportunity_decision_as_of(
                        episode.episode_key, decision_as_of=131
                    )
        self.assertEqual(frozen.decision_as_of, 130)
        self.assertEqual(same.decision_as_of, 130)

    def test_causal_loader_hides_later_trigger(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._assign(key="t1", observed=100, chain=95)
                self._assign(key="t2", observed=120, chain=115)
                early = load_market_opportunity_episode_triggers(
                    episode.episode_key, as_of=110
                )
                all_rows = load_market_opportunity_episode_triggers(episode.episode_key)
        self.assertEqual([item.trigger_key for item in early], ["t1"])
        self.assertEqual([item.trigger_key for item in all_rows], ["t1", "t2"])

    def test_later_exact_trigger_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = self._assign(key="same", observed=100, chain=95)
                repeated = self._assign(key="same", observed=120, chain=95)
                triggers = load_market_opportunity_episode_triggers(first.episode_key)
                conflicts = count_market_trigger_replay_conflicts(acquisition_run_key="run-a")
        self.assertEqual(first.episode_key, repeated.episode_key)
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].observed_at, 100)
        self.assertEqual(conflicts, 0)

    def test_later_conflicting_trigger_replay_is_audited_and_first_trigger_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = self._assign(key="same", observed=100, chain=95)
                repeated = self._assign(
                    key="same",
                    token="OTHER",
                    observed=120,
                    chain=95,
                    direction="downward_pressure",
                )
                triggers = load_market_opportunity_episode_triggers(first.episode_key)
                conflicts = count_market_trigger_replay_conflicts(acquisition_run_key="run-a")
        self.assertEqual(first.episode_key, repeated.episode_key)
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].token_mint, "T")
        self.assertEqual(triggers[0].direction, "upward_pressure")
        self.assertEqual(conflicts, 1)

    def test_earlier_same_key_replay_does_not_retroactively_backdate_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = self._assign(key="same", observed=120, chain=95)
                repeated = self._assign(key="same", observed=110, chain=95)
                triggers = load_market_opportunity_episode_triggers(first.episode_key)
                conflicts = count_market_trigger_replay_conflicts(acquisition_run_key="run-a")
        self.assertEqual(first.episode_key, repeated.episode_key)
        self.assertEqual(triggers[0].observed_at, 120)
        self.assertEqual(conflicts, 1)

    def test_impossible_trigger_clock_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with self.assertRaises(ValueError):
                    self._assign(observed=99, chain=100)

    def test_transient_sqlite_lock_retries_complete_transaction(self):
        attempts = []

        def operation():
            attempts.append(len(attempts) + 1)
            if len(attempts) < 3:
                raise sqlite3.OperationalError("database is locked")
            return "ok"

        with patch("src.market_opportunity_episode_store.time.sleep") as sleep:
            result = _run_with_sqlite_lock_retry(operation)

        self.assertEqual(result, "ok")
        self.assertEqual(attempts, [1, 2, 3])
        sleep.assert_has_calls([call(0.05), call(0.20)])

    def test_non_lock_sqlite_operational_error_is_not_retried(self):
        attempts = []

        def operation():
            attempts.append(1)
            raise sqlite3.OperationalError("no such table: broken")

        with patch("src.market_opportunity_episode_store.time.sleep") as sleep:
            with self.assertRaises(sqlite3.OperationalError):
                _run_with_sqlite_lock_retry(operation)

        self.assertEqual(attempts, [1])
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
