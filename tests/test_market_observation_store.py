import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import (
    load_latest_market_lifecycle,
    load_market_trades,
    record_market_lifecycle,
    record_market_trade,
)
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation


class MarketObservationStoreTests(unittest.TestCase):
    def test_trade_store_is_run_scoped_and_causal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                a = MarketTradeObservation("T", "buy", 100, 105, "W1", 10.0, 1.0, "pump")
                b = MarketTradeObservation("T", "sell", 110, 120, "W2", 5.0, 1.1, "pump")
                record_market_trade(acquisition_run_key="run-a", event_key="a", source_provider="native", observation=a)
                record_market_trade(acquisition_run_key="run-a", event_key="b", source_provider="native", observation=b)
                record_market_trade(acquisition_run_key="run-b", event_key="c", source_provider="native", observation=a)
                early = load_market_trades(acquisition_run_key="run-a", token_mint="T", as_of=110)
                all_a = load_market_trades(acquisition_run_key="run-a", token_mint="T")
                all_b = load_market_trades(acquisition_run_key="run-b", token_mint="T")
        self.assertEqual([item.event_key for item in early], ["a"])
        self.assertEqual([item.event_key for item in all_a], ["a", "b"])
        self.assertEqual([item.event_key for item in all_b], ["c"])

    def test_trade_insert_is_idempotent_and_conflict_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                event = MarketTradeObservation("T", "buy", 100, 105, "W", 10.0, 1.0, "pump")
                self.assertTrue(record_market_trade(acquisition_run_key="run", event_key="e", source_provider="native", observation=event))
                self.assertFalse(record_market_trade(acquisition_run_key="run", event_key="e", source_provider="native", observation=event))
                changed = MarketTradeObservation("T", "sell", 100, 105, "W", 10.0, 1.0, "pump")
                with self.assertRaises(ValueError):
                    record_market_trade(acquisition_run_key="run", event_key="e", source_provider="native", observation=changed)

    def test_trade_later_replay_preserves_first_seen_availability(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = MarketTradeObservation(
                    "T", "buy", 100, 105, "W", None, None, "pump", "signature"
                )
                replay = MarketTradeObservation(
                    "T", "buy", 100, 112, "W", None, None, "pump", "signature"
                )
                self.assertTrue(
                    record_market_trade(
                        acquisition_run_key="run",
                        event_key="pump:signature:0",
                        source_provider="native",
                        observation=first,
                    )
                )
                self.assertFalse(
                    record_market_trade(
                        acquisition_run_key="run",
                        event_key="pump:signature:0",
                        source_provider="native",
                        observation=replay,
                    )
                )
                loaded = load_market_trades(acquisition_run_key="run", token_mint="T")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].observation.observed_at, 105)

    def test_trade_replay_cannot_backdate_first_seen_availability(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = MarketTradeObservation(
                    "T", "buy", 100, 110, "W", None, None, "pump", "signature"
                )
                backdated = MarketTradeObservation(
                    "T", "buy", 100, 105, "W", None, None, "pump", "signature"
                )
                record_market_trade(
                    acquisition_run_key="run",
                    event_key="pump:signature:0",
                    source_provider="native",
                    observation=first,
                )
                with self.assertRaisesRegex(ValueError, "precedes first observation"):
                    record_market_trade(
                        acquisition_run_key="run",
                        event_key="pump:signature:0",
                        source_provider="native",
                        observation=backdated,
                    )

    def test_chain_time_filter_preserves_market_window_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                for key, chain in (("old", 100), ("new", 200)):
                    record_market_trade(
                        acquisition_run_key="run",
                        event_key=key,
                        source_provider="native",
                        observation=MarketTradeObservation("T", "buy", chain, chain + 1, key),
                    )
                rows = load_market_trades(acquisition_run_key="run", token_mint="T", chain_time_after=150)
        self.assertEqual([item.event_key for item in rows], ["new"])

    def test_lifecycle_store_respects_availability_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_market_lifecycle(
                    acquisition_run_key="run",
                    event_key="start",
                    source_provider="native",
                    observation=MarketLifecycleObservation("T", 100, 105, "pump"),
                )
                self.assertIsNone(load_latest_market_lifecycle(acquisition_run_key="run", token_mint="T", as_of=104))
                loaded = load_latest_market_lifecycle(acquisition_run_key="run", token_mint="T", as_of=105)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.observation.market_started_at, 100)

    def test_lifecycle_insert_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                item = MarketLifecycleObservation("T", 100, 105, "pump")
                self.assertTrue(record_market_lifecycle(acquisition_run_key="run", event_key="start", source_provider="native", observation=item))
                self.assertFalse(record_market_lifecycle(acquisition_run_key="run", event_key="start", source_provider="native", observation=item))

    def test_lifecycle_later_replay_preserves_first_seen_availability(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                first = MarketLifecycleObservation("T", 100, 105, "pump")
                replay = MarketLifecycleObservation("T", 100, 115, "pump")
                self.assertTrue(
                    record_market_lifecycle(
                        acquisition_run_key="run",
                        event_key="pump-create:signature:0",
                        source_provider="native",
                        observation=first,
                    )
                )
                self.assertFalse(
                    record_market_lifecycle(
                        acquisition_run_key="run",
                        event_key="pump-create:signature:0",
                        source_provider="native",
                        observation=replay,
                    )
                )
                loaded = load_latest_market_lifecycle(
                    acquisition_run_key="run", token_mint="T"
                )
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.observation.observed_at, 105)

    def test_impossible_clock_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with self.assertRaises(ValueError):
                    record_market_trade(
                        acquisition_run_key="run",
                        event_key="bad",
                        source_provider="native",
                        observation=MarketTradeObservation("T", "buy", 100, 99, "W"),
                    )


if __name__ == "__main__":
    unittest.main()
