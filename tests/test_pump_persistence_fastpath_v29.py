import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import load_market_trades
from src.pump_bonding_stream import PumpCreateEvent, PumpLogNotification, PumpTradeEvent
from src.pump_microbatch_persistence import persist_pump_notifications_microbatch
from src.pump_persistence_fastpath_v29 import (
    persist_pump_notifications_microbatch_fast_v29,
    pump_persistence_fastpath_snapshot,
    reset_pump_persistence_fastpath_metrics,
)


def _notification(
    *,
    signature: str,
    observed_at: int,
    token_mint: str,
) -> PumpLogNotification:
    return PumpLogNotification(
        signature=signature,
        slot=1,
        observed_at=observed_at,
        events=(
            PumpTradeEvent(token_mint, 100, 200, True, "W1", observed_at - 1),
            PumpTradeEvent(token_mint, 120, 180, False, "W2", observed_at - 1),
        ),
        lifecycle_events=(
            PumpCreateEvent(token_mint, "CURVE", "USER", "CREATOR", observed_at - 2),
        ),
    )


class PumpPersistenceFastPathV29Tests(unittest.TestCase):
    def test_conflicting_replay_matches_existing_microbatch_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pump-fast-v29.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                later = _notification(
                    signature="same",
                    observed_at=1100,
                    token_mint="OLD",
                )
                earlier = _notification(
                    signature="same",
                    observed_at=1050,
                    token_mint="NEW",
                )
                legacy = persist_pump_notifications_microbatch(
                    (later, earlier),
                    acquisition_run_key="legacy",
                )

                reset_pump_persistence_fastpath_metrics()
                fast = persist_pump_notifications_microbatch_fast_v29(
                    (later, earlier),
                    acquisition_run_key="fast",
                )
                snapshot = pump_persistence_fastpath_snapshot()

                legacy_new = load_market_trades(acquisition_run_key="legacy", token_mint="NEW")
                fast_new = load_market_trades(acquisition_run_key="fast", token_mint="NEW")
                fast_old = load_market_trades(acquisition_run_key="fast", token_mint="OLD")

        self.assertEqual(legacy, fast)
        self.assertEqual(len(legacy_new), 2)
        self.assertEqual(len(fast_new), 2)
        self.assertEqual(fast_old, ())
        self.assertTrue(all(item.observation.observed_at == 1050 for item in fast_new))
        self.assertEqual(snapshot.trade_insert_attempts, 4)
        self.assertEqual(snapshot.trade_collision_reads, 2)
        self.assertEqual(snapshot.lifecycle_insert_attempts, 2)
        self.assertEqual(snapshot.lifecycle_collision_reads, 1)

    def test_new_rows_do_not_issue_replay_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pump-fast-v29-new.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                batch = tuple(
                    _notification(
                        signature=f"sig-{index}",
                        observed_at=1000 + index,
                        token_mint=f"TOKEN-{index}",
                    )
                    for index in range(12)
                )
                reset_pump_persistence_fastpath_metrics()
                results = persist_pump_notifications_microbatch_fast_v29(
                    batch,
                    acquisition_run_key="run",
                )
                snapshot = pump_persistence_fastpath_snapshot()

        self.assertEqual(len(results), 12)
        self.assertTrue(all(result.newly_persisted_trades == 2 for result in results))
        self.assertEqual(snapshot.trade_insert_attempts, 24)
        self.assertEqual(snapshot.trade_collision_reads, 0)
        self.assertEqual(snapshot.lifecycle_insert_attempts, 12)
        self.assertEqual(snapshot.lifecycle_collision_reads, 0)


if __name__ == "__main__":
    unittest.main()
