import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.pump_batch_persistence import persist_pump_notification_batch
from src.pump_bonding_stream import PumpCreateEvent, PumpLogNotification, PumpTradeEvent
from src.pump_radar_bridge_v4 import evaluate_persisted_pump_notification_for_radar_v4


class PumpRadarBridgeV4Tests(unittest.TestCase):
    def test_persist_then_evaluate_opens_fresh_episode(self):
        events = tuple(
            PumpTradeEvent(
                mint="TOKEN",
                sol_amount=100 + i,
                token_amount=1000,
                is_buy=True,
                user=f"W{i}",
                timestamp=976 + i * 4,
            )
            for i in range(6)
        )
        notification = PumpLogNotification(
            signature="sig",
            slot=1,
            observed_at=1000,
            events=events,
            lifecycle_events=(PumpCreateEvent("TOKEN", "CURVE", "USER", "CREATOR", 930),),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                persisted = persist_pump_notification_batch(
                    notification, acquisition_run_key="run"
                )
                result = evaluate_persisted_pump_notification_for_radar_v4(
                    notification,
                    acquisition_run_key="run",
                    persist_result=persisted,
                )

        self.assertEqual(result.newly_persisted_trades, 6)
        self.assertEqual(result.affected_tokens, ("TOKEN",))
        self.assertEqual(len(result.hits), 1)
        self.assertEqual(result.hits[0].trigger.trigger_kind, "fresh_market_burst")

    def test_signature_mismatch_is_rejected(self):
        notification = PumpLogNotification("sig", 1, 1000, (), ())
        from src.pump_batch_persistence import PumpBatchPersistResult

        mismatched = PumpBatchPersistResult("other", 0, 0, 0, 0, ())
        with self.assertRaises(ValueError):
            evaluate_persisted_pump_notification_for_radar_v4(
                notification,
                acquisition_run_key="run",
                persist_result=mismatched,
            )


if __name__ == "__main__":
    unittest.main()
