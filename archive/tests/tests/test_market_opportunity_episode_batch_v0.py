from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src import database
from src.market_opportunity_episode_batch_v0 import (
    MarketContinuationTriggerWriteV0,
    record_market_continuation_triggers_batch_v0,
)
from src.market_opportunity_episode_store import (
    assign_market_opportunity_trigger,
    load_market_opportunity_episode_triggers,
)


class MarketOpportunityEpisodeBatchV0Tests(unittest.TestCase):
    def _item(self, *, episode_key: str, trigger_key: str = "TR2", observed_at: int = 110):
        return MarketContinuationTriggerWriteV0(
            acquisition_run_key="RUN",
            episode_key=episode_key,
            trigger_key=trigger_key,
            token_mint="TOKEN",
            trigger_kind="activity_acceleration",
            direction="upward_pressure",
            chain_time=observed_at,
            observed_at=observed_at,
            method_version="radar-v0",
            venue="pump",
        )

    def test_batch_persists_only_inside_existing_episode_and_replays_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            isolated = replace(database.settings, database_path=Path(directory) / "test.db")
            with patch.object(database, "settings", isolated):
                episode = assign_market_opportunity_trigger(
                    acquisition_run_key="RUN",
                    trigger_key="TR1",
                    token_mint="TOKEN",
                    trigger_kind="activity_acceleration",
                    direction="upward_pressure",
                    chain_time=100,
                    observed_at=100,
                    method_version="radar-v0",
                    venue="pump",
                )
                first = record_market_continuation_triggers_batch_v0(
                    (self._item(episode_key=episode.episode_key),)
                )
                replay = record_market_continuation_triggers_batch_v0(
                    (self._item(episode_key=episode.episode_key),)
                )
                rows = load_market_opportunity_episode_triggers(episode.episode_key)

            self.assertEqual(first.inserted, 1)
            self.assertEqual(first.replayed, 0)
            self.assertEqual(replay.inserted, 0)
            self.assertEqual(replay.replayed, 1)
            self.assertEqual([item.trigger_key for item in rows], ["TR1", "TR2"])

    def test_batch_cannot_write_first_trigger_or_cross_episode_window(self):
        with tempfile.TemporaryDirectory() as directory:
            isolated = replace(database.settings, database_path=Path(directory) / "test.db")
            with patch.object(database, "settings", isolated):
                episode = assign_market_opportunity_trigger(
                    acquisition_run_key="RUN",
                    trigger_key="TR1",
                    token_mint="TOKEN",
                    trigger_kind="activity_acceleration",
                    direction="upward_pressure",
                    chain_time=100,
                    observed_at=100,
                    method_version="radar-v0",
                    venue="pump",
                )
                with self.assertRaises(ValueError):
                    record_market_continuation_triggers_batch_v0(
                        (self._item(episode_key=episode.episode_key, trigger_key="TR1"),)
                    )
                with self.assertRaises(ValueError):
                    record_market_continuation_triggers_batch_v0(
                        (self._item(episode_key=episode.episode_key, observed_at=160),)
                    )


if __name__ == "__main__":
    unittest.main()
