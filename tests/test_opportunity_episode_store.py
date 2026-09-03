import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.opportunity_episode_store import (
    assign_opportunity_trigger,
    freeze_opportunity_decision_as_of,
    load_opportunity_episode_triggers,
)


class OpportunityEpisodeStoreTests(unittest.TestCase):
    def test_same_token_within_60_seconds_joins_same_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = assign_opportunity_trigger(
                    acquisition_run_key="acq-1",
                    observation_key="obs-1",
                    wallet_address="W1",
                    token_mint="TOKEN",
                    chain_time=100,
                    observed_at=110,
                )
                second = assign_opportunity_trigger(
                    acquisition_run_key="acq-1",
                    observation_key="obs-2",
                    wallet_address="W2",
                    token_mint="TOKEN",
                    chain_time=150,
                    observed_at=169,
                )
                triggers = load_opportunity_episode_triggers(first.episode_key)

        self.assertEqual(first.episode_key, second.episode_key)
        self.assertEqual(len(triggers), 2)
        self.assertEqual({item.wallet_address for item in triggers}, {"W1", "W2"})

    def test_trigger_at_exact_60_second_boundary_starts_new_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "boundary.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = assign_opportunity_trigger(
                    acquisition_run_key="acq-1",
                    observation_key="obs-1",
                    wallet_address="W1",
                    token_mint="TOKEN",
                    chain_time=100,
                    observed_at=110,
                )
                second = assign_opportunity_trigger(
                    acquisition_run_key="acq-1",
                    observation_key="obs-2",
                    wallet_address="W2",
                    token_mint="TOKEN",
                    chain_time=160,
                    observed_at=170,
                )

        self.assertNotEqual(first.episode_key, second.episode_key)

    def test_same_token_never_crosses_acquisition_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = assign_opportunity_trigger(
                    acquisition_run_key="acq-1",
                    observation_key="obs-1",
                    wallet_address="W",
                    token_mint="TOKEN",
                    chain_time=100,
                    observed_at=110,
                )
                second = assign_opportunity_trigger(
                    acquisition_run_key="acq-2",
                    observation_key="obs-2",
                    wallet_address="W",
                    token_mint="TOKEN",
                    chain_time=101,
                    observed_at=111,
                )

        self.assertNotEqual(first.episode_key, second.episode_key)

    def test_trigger_assignment_is_idempotent_and_rejects_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "idempotent.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = assign_opportunity_trigger(
                    acquisition_run_key="acq",
                    observation_key="obs",
                    wallet_address="W",
                    token_mint="TOKEN",
                    chain_time=100,
                    observed_at=110,
                )
                same = assign_opportunity_trigger(
                    acquisition_run_key="acq",
                    observation_key="obs",
                    wallet_address="W",
                    token_mint="TOKEN",
                    chain_time=100,
                    observed_at=110,
                )
                with self.assertRaises(ValueError):
                    assign_opportunity_trigger(
                        acquisition_run_key="acq",
                        observation_key="obs",
                        wallet_address="OTHER",
                        token_mint="TOKEN",
                        chain_time=100,
                        observed_at=110,
                    )

        self.assertEqual(first, same)

    def test_decision_as_of_is_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decision.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = assign_opportunity_trigger(
                    acquisition_run_key="acq",
                    observation_key="obs",
                    wallet_address="W",
                    token_mint="TOKEN",
                    chain_time=100,
                    observed_at=110,
                )
                frozen = freeze_opportunity_decision_as_of(
                    episode.episode_key,
                    decision_as_of=115,
                )
                same = freeze_opportunity_decision_as_of(
                    episode.episode_key,
                    decision_as_of=115,
                )
                with self.assertRaises(ValueError):
                    freeze_opportunity_decision_as_of(
                        episode.episode_key,
                        decision_as_of=116,
                    )

        self.assertEqual(frozen.decision_as_of, 115)
        self.assertEqual(same.decision_as_of, 115)

    def test_as_of_loader_hides_later_triggers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "causal.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = assign_opportunity_trigger(
                    acquisition_run_key="acq",
                    observation_key="obs-1",
                    wallet_address="W1",
                    token_mint="TOKEN",
                    chain_time=100,
                    observed_at=110,
                )
                assign_opportunity_trigger(
                    acquisition_run_key="acq",
                    observation_key="obs-2",
                    wallet_address="W2",
                    token_mint="TOKEN",
                    chain_time=120,
                    observed_at=130,
                )
                causal = load_opportunity_episode_triggers(
                    episode.episode_key,
                    as_of=115,
                )
                all_triggers = load_opportunity_episode_triggers(episode.episode_key)

        self.assertEqual([item.observation_key for item in causal], ["obs-1"])
        self.assertEqual(len(all_triggers), 2)

    def test_invalid_clock_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clock.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with self.assertRaises(ValueError):
                    assign_opportunity_trigger(
                        acquisition_run_key="acq",
                        observation_key="obs",
                        wallet_address="W",
                        token_mint="TOKEN",
                        chain_time=120,
                        observed_at=110,
                    )


if __name__ == "__main__":
    unittest.main()
