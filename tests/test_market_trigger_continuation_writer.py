import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_opportunity_episode_store import (
    assign_market_opportunity_trigger,
    count_market_trigger_replay_conflicts,
    load_market_opportunity_episode_triggers,
)
from src.market_trigger_continuation_writer import (
    ContinuationTriggerRecord,
    MarketTriggerContinuationWriter,
    _persist_continuation_batch_db_stage,
)


class ContinuationTriggerWriterTests(unittest.TestCase):
    def _record(self, episode, *, key, observed, direction="upward_pressure"):
        return ContinuationTriggerRecord(
            acquisition_run_key="run-a",
            episode_key=episode.episode_key,
            trigger_key=key,
            token_mint="T",
            trigger_kind="activity_acceleration",
            direction=direction,
            chain_time=observed - 1,
            observed_at=observed,
            method_version="market_opportunity_radar_v1",
            venue="pump_bonding_curve",
        )

    def test_batch_appends_continuations_without_opening_new_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "continuations.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = assign_market_opportunity_trigger(
                    acquisition_run_key="run-a",
                    trigger_key="t1",
                    token_mint="T",
                    trigger_kind="activity_acceleration",
                    direction="upward_pressure",
                    chain_time=99,
                    observed_at=100,
                    method_version="market_opportunity_radar_v1",
                    venue="pump_bonding_curve",
                )
                results, _, _ = _persist_continuation_batch_db_stage(
                    (
                        self._record(episode, key="t2", observed=120),
                        self._record(episode, key="t3", observed=130),
                    )
                )
                triggers = load_market_opportunity_episode_triggers(episode.episode_key)
                with database.connection() as conn:
                    row = conn.execute(
                        "SELECT COUNT(*) AS n FROM market_opportunity_episodes WHERE acquisition_run_key=?",
                        ("run-a",),
                    ).fetchone()

        self.assertEqual([item.episode_key for item in results], [episode.episode_key] * 2)
        self.assertEqual([item.trigger_key for item in triggers], ["t1", "t2", "t3"])
        self.assertEqual(int(row["n"]), 1)

    def test_exact_continuation_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "continuations.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = assign_market_opportunity_trigger(
                    acquisition_run_key="run-a",
                    trigger_key="t1",
                    token_mint="T",
                    trigger_kind="activity_acceleration",
                    direction="upward_pressure",
                    chain_time=99,
                    observed_at=100,
                    method_version="market_opportunity_radar_v1",
                    venue="pump_bonding_curve",
                )
                record = self._record(episode, key="same", observed=120)
                _persist_continuation_batch_db_stage((record,))
                _persist_continuation_batch_db_stage((record,))
                triggers = load_market_opportunity_episode_triggers(episode.episode_key)
                conflicts = count_market_trigger_replay_conflicts(
                    acquisition_run_key="run-a"
                )

        self.assertEqual([item.trigger_key for item in triggers], ["t1", "same"])
        self.assertEqual(conflicts, 0)

    def test_conflicting_continuation_replay_keeps_first_and_is_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "continuations.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = assign_market_opportunity_trigger(
                    acquisition_run_key="run-a",
                    trigger_key="t1",
                    token_mint="T",
                    trigger_kind="activity_acceleration",
                    direction="upward_pressure",
                    chain_time=99,
                    observed_at=100,
                    method_version="market_opportunity_radar_v1",
                    venue="pump_bonding_curve",
                )
                _persist_continuation_batch_db_stage(
                    (self._record(episode, key="same", observed=120),)
                )
                _persist_continuation_batch_db_stage(
                    (
                        self._record(
                            episode,
                            key="same",
                            observed=120,
                            direction="downward_pressure",
                        ),
                    )
                )
                triggers = load_market_opportunity_episode_triggers(episode.episode_key)
                conflicts = count_market_trigger_replay_conflicts(
                    acquisition_run_key="run-a"
                )

        self.assertEqual(len(triggers), 2)
        self.assertEqual(triggers[1].direction, "upward_pressure")
        self.assertEqual(conflicts, 1)

    def test_record_outside_episode_window_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "continuations.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = assign_market_opportunity_trigger(
                    acquisition_run_key="run-a",
                    trigger_key="t1",
                    token_mint="T",
                    trigger_kind="activity_acceleration",
                    direction="upward_pressure",
                    chain_time=99,
                    observed_at=100,
                    method_version="market_opportunity_radar_v1",
                    venue="pump_bonding_curve",
                )
                with self.assertRaises(RuntimeError):
                    _persist_continuation_batch_db_stage(
                        (self._record(episode, key="t2", observed=160),)
                    )


class ContinuationTriggerThreadedWriterTests(unittest.IsolatedAsyncioTestCase):
    async def test_threaded_writer_batches_and_drains(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "continuations.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = assign_market_opportunity_trigger(
                    acquisition_run_key="run-a",
                    trigger_key="t1",
                    token_mint="T",
                    trigger_kind="activity_acceleration",
                    direction="upward_pressure",
                    chain_time=99,
                    observed_at=100,
                    method_version="market_opportunity_radar_v1",
                    venue="pump_bonding_curve",
                )
                writer = MarketTriggerContinuationWriter(batch_size=8, max_wait_ms=20)
                records = [
                    ContinuationTriggerRecord(
                        acquisition_run_key="run-a",
                        episode_key=episode.episode_key,
                        trigger_key=f"t{index}",
                        token_mint="T",
                        trigger_kind="activity_acceleration",
                        direction="upward_pressure",
                        chain_time=100 + index,
                        observed_at=101 + index,
                        method_version="market_opportunity_radar_v1",
                        venue="pump_bonding_curve",
                    )
                    for index in range(2, 6)
                ]
                futures = [writer.enqueue(record) for record in records]
                results = await asyncio.gather(
                    *(asyncio.wrap_future(future) for future in futures)
                )
                await writer.close(cancel_pending=False)
                triggers = load_market_opportunity_episode_triggers(episode.episode_key)

        self.assertEqual(len(results), 4)
        self.assertEqual(len(triggers), 5)
        self.assertEqual(writer.queue_size, 0)
        self.assertIsNone(writer.fatal_exception)
        self.assertGreaterEqual(max(writer.batch_sizes), 2)


if __name__ == "__main__":
    unittest.main()
