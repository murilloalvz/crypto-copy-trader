import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import load_market_trades
from src.pump_bonding_stream import PumpLogNotification, PumpTradeEvent
from src.pump_microbatch_persistence import persist_pump_notifications_microbatch


def _notification(signature: str, *, observed_at: int, mint: str = "TOKEN") -> PumpLogNotification:
    return PumpLogNotification(
        signature=signature,
        slot=1,
        observed_at=observed_at,
        events=(PumpTradeEvent(mint, 100, 200, True, "W", 1000),),
        lifecycle_events=(),
    )


class PumpMicrobatchPersistenceTests(unittest.TestCase):
    def test_multiple_notifications_commit_in_input_order_with_individual_results(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                results = persist_pump_notifications_microbatch(
                    (
                        _notification("sig-a", observed_at=1005, mint="A"),
                        _notification("sig-b", observed_at=1006, mint="B"),
                        _notification("sig-c", observed_at=1007, mint="C"),
                    ),
                    acquisition_run_key="run",
                )
                a = load_market_trades(acquisition_run_key="run", token_mint="A")
                b = load_market_trades(acquisition_run_key="run", token_mint="B")
                c = load_market_trades(acquisition_run_key="run", token_mint="C")

        self.assertEqual([item.signature for item in results], ["sig-a", "sig-b", "sig-c"])
        self.assertTrue(all(item.newly_persisted_trades == 1 for item in results))
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)
        self.assertEqual(len(c), 1)

    def test_replay_inside_same_microbatch_keeps_earliest_observed_at(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                results = persist_pump_notifications_microbatch(
                    (
                        _notification("same", observed_at=1010),
                        _notification("same", observed_at=1005),
                    ),
                    acquisition_run_key="run",
                )
                rows = load_market_trades(acquisition_run_key="run", token_mint="TOKEN")

        self.assertEqual(results[0].newly_persisted_trades, 1)
        self.assertEqual(results[1].duplicate_or_replayed_trades, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].observation.observed_at, 1005)

    def test_empty_microbatch_is_noop(self):
        self.assertEqual(
            persist_pump_notifications_microbatch((), acquisition_run_key="run"),
            (),
        )


if __name__ == "__main__":
    unittest.main()
