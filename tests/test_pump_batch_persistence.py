import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import load_latest_market_lifecycle, load_market_trades
from src.pump_batch_persistence import persist_pump_notification_batch
from src.pump_bonding_stream import PumpCreateEvent, PumpLogNotification, PumpTradeEvent


class PumpBatchPersistenceTests(unittest.TestCase):
    def _notification(self, *, observed_at: int = 1005) -> PumpLogNotification:
        return PumpLogNotification(
            signature="sig",
            slot=1,
            observed_at=observed_at,
            events=(
                PumpTradeEvent("TOKEN", 100, 200, True, "W1", 1000),
                PumpTradeEvent("TOKEN", 120, 180, False, "W2", 1001),
                PumpTradeEvent("IGNORED", 0, 50, True, "W3", 1002),
            ),
            lifecycle_events=(
                PumpCreateEvent("TOKEN", "CURVE", "USER", "CREATOR", 999),
            ),
        )

    def test_batch_persists_trades_and_lifecycle_in_one_semantic_unit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                result = persist_pump_notification_batch(
                    self._notification(), acquisition_run_key="run"
                )
                rows = load_market_trades(acquisition_run_key="run", token_mint="TOKEN")
                ignored = load_market_trades(acquisition_run_key="run", token_mint="IGNORED")
                lifecycle = load_latest_market_lifecycle(
                    acquisition_run_key="run", token_mint="TOKEN", venue="pump_bonding_curve"
                )

        self.assertEqual(result.newly_persisted_trades, 2)
        self.assertEqual(result.newly_persisted_lifecycle, 1)
        self.assertEqual(result.affected_tokens, ("TOKEN",))
        self.assertEqual([item.observation.side for item in rows], ["buy", "sell"])
        self.assertEqual(ignored, ())
        self.assertIsNotNone(lifecycle)

    def test_later_replay_is_idempotent_and_backdating_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = persist_pump_notification_batch(
                    self._notification(observed_at=1005), acquisition_run_key="run"
                )
                replay = persist_pump_notification_batch(
                    self._notification(observed_at=1010), acquisition_run_key="run"
                )
                with self.assertRaises(ValueError):
                    persist_pump_notification_batch(
                        self._notification(observed_at=1004), acquisition_run_key="run"
                    )

        self.assertEqual(first.newly_persisted_trades, 2)
        self.assertEqual(replay.newly_persisted_trades, 0)
        self.assertEqual(replay.duplicate_or_replayed_trades, 2)
        self.assertEqual(replay.duplicate_or_replayed_lifecycle, 1)


if __name__ == "__main__":
    unittest.main()
