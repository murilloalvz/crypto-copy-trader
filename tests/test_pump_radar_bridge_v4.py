import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.pump_batch_persistence import PumpBatchPersistResult, persist_pump_notification_batch
from src.pump_bonding_stream import PumpCreateEvent, PumpLogNotification, PumpTradeEvent
from src.pump_radar_bridge_v4 import evaluate_persisted_pump_notification_for_radar_v4


class PumpRadarBridgeV4Tests(unittest.TestCase):
    def test_ordered_distinct_transactions_open_fresh_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                last_result = None
                for i in range(6):
                    notification = PumpLogNotification(
                        signature=f"sig-{i}",
                        slot=1 + i,
                        observed_at=980 + i * 4,
                        events=(
                            PumpTradeEvent(
                                mint="TOKEN",
                                sol_amount=100 + i,
                                token_amount=1000,
                                is_buy=True,
                                user=f"W{i}",
                                timestamp=979 + i * 4,
                            ),
                        ),
                        lifecycle_events=(
                            (PumpCreateEvent("TOKEN", "CURVE", "USER", "CREATOR", 930),)
                            if i == 0
                            else ()
                        ),
                    )
                    persisted = persist_pump_notification_batch(
                        notification, acquisition_run_key="run"
                    )
                    last_result = evaluate_persisted_pump_notification_for_radar_v4(
                        notification,
                        acquisition_run_key="run",
                        persist_result=persisted,
                    )

        self.assertIsNotNone(last_result)
        assert last_result is not None
        self.assertEqual(last_result.affected_tokens, ("TOKEN",))
        self.assertEqual(len(last_result.hits), 1)
        self.assertEqual(last_result.hits[0].trigger.trigger_kind, "fresh_market_burst")

    def test_signature_mismatch_is_rejected(self):
        notification = PumpLogNotification("sig", 1, 1000, (), ())
        mismatched = PumpBatchPersistResult(
            signature="other",
            newly_persisted_trades=0,
            duplicate_or_replayed_trades=0,
            conflicting_trades=0,
            newly_persisted_lifecycle=0,
            duplicate_or_replayed_lifecycle=0,
            conflicting_lifecycle=0,
            affected_tokens=(),
        )
        with self.assertRaises(ValueError):
            evaluate_persisted_pump_notification_for_radar_v4(
                notification,
                acquisition_run_key="run",
                persist_result=mismatched,
            )


if __name__ == "__main__":
    unittest.main()
