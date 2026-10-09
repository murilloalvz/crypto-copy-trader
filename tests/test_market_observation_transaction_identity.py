import sqlite3
import tempfile
import unittest
from contextlib import closing
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


class MarketObservationTransactionIdentityTests(unittest.TestCase):
    def test_transaction_identity_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                item = MarketTradeObservation(
                    token_mint="T",
                    side="buy",
                    chain_time=100,
                    observed_at=101,
                    wallet_address="W",
                    venue="pump",
                    transaction_key="signature-1",
                )
                self.assertTrue(
                    record_market_trade(
                        acquisition_run_key="run",
                        event_key="e",
                        source_provider="native",
                        observation=item,
                    )
                )
                loaded = load_market_trades(acquisition_run_key="run", token_mint="T")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].observation.transaction_key, "signature-1")

    def test_existing_pre_transaction_identity_db_is_migrated_without_data_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with closing(sqlite3.connect(path)) as conn:
                with conn:
                    conn.execute(
                        """CREATE TABLE market_trade_observations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        acquisition_run_key TEXT NOT NULL,
                        event_key TEXT NOT NULL,
                        source_provider TEXT NOT NULL,
                        token_mint TEXT NOT NULL,
                        side TEXT NOT NULL,
                        chain_time INTEGER NOT NULL,
                        observed_at INTEGER NOT NULL,
                        wallet_address TEXT,
                        notional_usd REAL,
                        price_usd REAL,
                        venue TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(acquisition_run_key, event_key)
                        )"""
                    )
                    conn.execute(
                        """INSERT INTO market_trade_observations(
                        acquisition_run_key, event_key, source_provider, token_mint, side,
                        chain_time, observed_at, wallet_address, venue
                        ) VALUES ('old-run', 'old-event', 'native', 'T', 'buy', 90, 91, 'OLD', 'pump')"""
                    )

            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                item = MarketTradeObservation(
                    token_mint="T",
                    side="buy",
                    chain_time=100,
                    observed_at=101,
                    wallet_address="NEW",
                    venue="pump",
                    transaction_key="signature-new",
                )
                record_market_trade(
                    acquisition_run_key="new-run",
                    event_key="new-event",
                    source_provider="native",
                    observation=item,
                )
                old_rows = load_market_trades(acquisition_run_key="old-run", token_mint="T")
                new_rows = load_market_trades(acquisition_run_key="new-run", token_mint="T")

            with closing(sqlite3.connect(path)) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(market_trade_observations)")}

        self.assertIn("transaction_key", columns)
        self.assertEqual(len(old_rows), 1)
        self.assertIsNone(old_rows[0].observation.transaction_key)
        self.assertEqual(new_rows[0].observation.transaction_key, "signature-new")

    def test_slot_and_creator_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                trade = MarketTradeObservation(
                    token_mint="T",
                    side="buy",
                    chain_time=100,
                    observed_at=101,
                    venue="pump",
                    slot=12345,
                )
                record_market_trade(
                    acquisition_run_key="run",
                    event_key="e",
                    source_provider="native",
                    observation=trade,
                )
                lifecycle = MarketLifecycleObservation(
                    token_mint="T",
                    market_started_at=90,
                    observed_at=91,
                    venue="pump",
                    creator="CREATOR_WALLET",
                    creation_slot=12300,
                )
                record_market_lifecycle(
                    acquisition_run_key="run",
                    event_key="create-e",
                    source_provider="native",
                    observation=lifecycle,
                )
                loaded_trades = load_market_trades(acquisition_run_key="run", token_mint="T")
                loaded_lifecycle = load_latest_market_lifecycle(acquisition_run_key="run", token_mint="T")
        self.assertEqual(loaded_trades[0].observation.slot, 12345)
        self.assertEqual(loaded_lifecycle.observation.creator, "CREATOR_WALLET")
        self.assertEqual(loaded_lifecycle.observation.creation_slot, 12300)

    def test_existing_pre_slot_creator_db_is_migrated_without_data_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with closing(sqlite3.connect(path)) as conn:
                with conn:
                    conn.execute(
                        """CREATE TABLE market_trade_observations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        acquisition_run_key TEXT NOT NULL,
                        event_key TEXT NOT NULL,
                        source_provider TEXT NOT NULL,
                        token_mint TEXT NOT NULL,
                        side TEXT NOT NULL,
                        chain_time INTEGER NOT NULL,
                        observed_at INTEGER NOT NULL,
                        wallet_address TEXT,
                        notional_usd REAL,
                        price_usd REAL,
                        venue TEXT,
                        transaction_key TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(acquisition_run_key, event_key)
                        )"""
                    )
                    conn.execute(
                        """INSERT INTO market_trade_observations(
                        acquisition_run_key, event_key, source_provider, token_mint, side,
                        chain_time, observed_at, wallet_address, venue
                        ) VALUES ('old-run', 'old-event', 'native', 'T', 'buy', 90, 91, 'OLD', 'pump')"""
                    )
                    conn.execute(
                        """CREATE TABLE market_lifecycle_observations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        acquisition_run_key TEXT NOT NULL,
                        event_key TEXT NOT NULL,
                        source_provider TEXT NOT NULL,
                        token_mint TEXT NOT NULL,
                        market_started_at INTEGER NOT NULL,
                        observed_at INTEGER NOT NULL,
                        venue TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(acquisition_run_key, event_key)
                        )"""
                    )
                    conn.execute(
                        """INSERT INTO market_lifecycle_observations(
                        acquisition_run_key, event_key, source_provider, token_mint,
                        market_started_at, observed_at, venue
                        ) VALUES ('old-run', 'old-create-event', 'native', 'T', 80, 81, 'pump')"""
                    )

            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_market_trade(
                    acquisition_run_key="new-run",
                    event_key="new-event",
                    source_provider="native",
                    observation=MarketTradeObservation(
                        token_mint="T", side="buy", chain_time=100, observed_at=101,
                        venue="pump", slot=999,
                    ),
                )
                record_market_lifecycle(
                    acquisition_run_key="new-run",
                    event_key="new-create-event",
                    source_provider="native",
                    observation=MarketLifecycleObservation(
                        token_mint="T", market_started_at=100, observed_at=101,
                        venue="pump", creator="NEW_CREATOR", creation_slot=998,
                    ),
                )
                old_trade_rows = load_market_trades(acquisition_run_key="old-run", token_mint="T")
                new_trade_rows = load_market_trades(acquisition_run_key="new-run", token_mint="T")
                old_lifecycle = load_latest_market_lifecycle(acquisition_run_key="old-run", token_mint="T")
                new_lifecycle = load_latest_market_lifecycle(acquisition_run_key="new-run", token_mint="T")

            with closing(sqlite3.connect(path)) as conn:
                trade_columns = {row[1] for row in conn.execute("PRAGMA table_info(market_trade_observations)")}
                lifecycle_columns = {row[1] for row in conn.execute("PRAGMA table_info(market_lifecycle_observations)")}

        self.assertIn("slot", trade_columns)
        self.assertIn("creator", lifecycle_columns)
        self.assertIn("creation_slot", lifecycle_columns)
        self.assertEqual(len(old_trade_rows), 1)
        self.assertIsNone(old_trade_rows[0].observation.slot)
        self.assertEqual(new_trade_rows[0].observation.slot, 999)
        self.assertIsNone(old_lifecycle.observation.creator)
        self.assertIsNone(old_lifecycle.observation.creation_slot)
        self.assertEqual(new_lifecycle.observation.creator, "NEW_CREATOR")
        self.assertEqual(new_lifecycle.observation.creation_slot, 998)


if __name__ == "__main__":
    unittest.main()
