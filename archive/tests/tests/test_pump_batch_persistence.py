import json
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
    def _notification(
        self,
        *,
        observed_at: int = 1005,
        first_trade_mint: str = "TOKEN",
        first_trade_user: str = "W1",
        lifecycle_mint: str = "TOKEN",
    ) -> PumpLogNotification:
        return PumpLogNotification(
            signature="sig",
            slot=1,
            observed_at=observed_at,
            events=(
                PumpTradeEvent(first_trade_mint, 100, 200, True, first_trade_user, 1000),
                PumpTradeEvent("TOKEN", 120, 180, False, "W2", 1001),
                PumpTradeEvent("IGNORED", 0, 50, True, "W3", 1002),
            ),
            lifecycle_events=(
                PumpCreateEvent(lifecycle_mint, "CURVE", "USER", "CREATOR", 999),
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
        self.assertEqual(result.conflicting_trades, 0)
        self.assertEqual(result.newly_persisted_lifecycle, 1)
        self.assertEqual(result.conflicting_lifecycle, 0)
        self.assertEqual(result.affected_tokens, ("TOKEN",))
        self.assertEqual([item.observation.side for item in rows], ["buy", "sell"])
        self.assertEqual(ignored, ())
        self.assertIsNotNone(lifecycle)

    def test_exact_replay_keeps_earliest_collector_timestamp_independent_of_write_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                later_write = persist_pump_notification_batch(
                    self._notification(observed_at=1010), acquisition_run_key="run"
                )
                earlier_replay = persist_pump_notification_batch(
                    self._notification(observed_at=1005), acquisition_run_key="run"
                )
                rows = load_market_trades(acquisition_run_key="run", token_mint="TOKEN")
                lifecycle = load_latest_market_lifecycle(
                    acquisition_run_key="run", token_mint="TOKEN", venue="pump_bonding_curve"
                )

        self.assertEqual(later_write.newly_persisted_trades, 2)
        self.assertEqual(earlier_replay.newly_persisted_trades, 0)
        self.assertEqual(earlier_replay.duplicate_or_replayed_trades, 2)
        self.assertEqual(earlier_replay.duplicate_or_replayed_lifecycle, 1)
        self.assertTrue(all(item.observation.observed_at == 1005 for item in rows))
        self.assertIsNotNone(lifecycle)
        self.assertEqual(lifecycle.observation.observed_at, 1005)

    def test_conflicting_later_replay_is_audited_and_does_not_replace_first_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                persist_pump_notification_batch(
                    self._notification(observed_at=1005), acquisition_run_key="run"
                )
                conflict = persist_pump_notification_batch(
                    self._notification(observed_at=1010, first_trade_mint="OTHER"),
                    acquisition_run_key="run",
                )
                canonical = load_market_trades(acquisition_run_key="run", token_mint="TOKEN")
                other = load_market_trades(acquisition_run_key="run", token_mint="OTHER")
                with database.connection() as conn:
                    audit = conn.execute(
                        """SELECT event_type, stored_observed_at, incoming_observed_at,
                            stored_identity_json, incoming_identity_json, canonical_action
                        FROM pump_replay_conflicts
                        WHERE acquisition_run_key='run' AND event_key='pump:sig:0'"""
                    ).fetchone()

        self.assertEqual(conflict.conflicting_trades, 1)
        self.assertEqual(len(canonical), 2)
        self.assertEqual(other, ())
        self.assertIsNotNone(audit)
        self.assertEqual(audit["event_type"], "trade")
        self.assertEqual(audit["stored_observed_at"], 1005)
        self.assertEqual(audit["incoming_observed_at"], 1010)
        self.assertEqual(audit["canonical_action"], "retain_earlier_observation")
        self.assertEqual(json.loads(audit["stored_identity_json"])[1], "TOKEN")
        self.assertEqual(json.loads(audit["incoming_identity_json"])[1], "OTHER")

    def test_conflicting_earlier_replay_replaces_later_write_and_is_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                persist_pump_notification_batch(
                    self._notification(observed_at=1010, first_trade_mint="OTHER"),
                    acquisition_run_key="run",
                )
                conflict = persist_pump_notification_batch(
                    self._notification(observed_at=1005, first_trade_mint="TOKEN"),
                    acquisition_run_key="run",
                )
                canonical = load_market_trades(acquisition_run_key="run", token_mint="TOKEN")
                other = load_market_trades(acquisition_run_key="run", token_mint="OTHER")
                with database.connection() as conn:
                    audit = conn.execute(
                        """SELECT canonical_action FROM pump_replay_conflicts
                        WHERE acquisition_run_key='run' AND event_key='pump:sig:0'"""
                    ).fetchone()

        self.assertEqual(conflict.conflicting_trades, 1)
        self.assertEqual(len(canonical), 2)
        self.assertEqual(other, ())
        first_trade = next(item for item in canonical if item.event_key == "pump:sig:0")
        self.assertEqual(first_trade.observation.observed_at, 1005)
        self.assertIsNotNone(audit)
        self.assertEqual(audit["canonical_action"], "replace_with_earlier_observation")


if __name__ == "__main__":
    unittest.main()
