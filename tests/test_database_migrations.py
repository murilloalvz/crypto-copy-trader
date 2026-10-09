import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.database import initialize_database


OLD_PAPER_TRADES_SCHEMA = """
CREATE TABLE paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_signature TEXT NOT NULL UNIQUE,
    wallet_address TEXT NOT NULL,
    token_mint TEXT,
    side TEXT NOT NULL,
    source_amount REAL NOT NULL,
    simulated_usd REAL NOT NULL,
    slippage_bps INTEGER NOT NULL,
    delay_seconds INTEGER NOT NULL,
    source_block_time INTEGER,
    market_price_usd REAL,
    execution_price_usd REAL,
    token_quantity REAL,
    fees_usd REAL,
    realized_pnl_usd REAL,
    price_error TEXT,
    status TEXT NOT NULL DEFAULT 'pending_price',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

OLD_WAVE_SIGNALS_SCHEMA = """
CREATE TABLE wave_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_mint TEXT NOT NULL,
    symbol TEXT,
    name TEXT,
    detected_at INTEGER NOT NULL,
    wave_score REAL NOT NULL,
    entry_market_price_usd REAL NOT NULL,
    entry_execution_price_usd REAL NOT NULL,
    copy_size_usd REAL NOT NULL,
    slippage_bps INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'tracking',
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(token_mint, detected_at)
);
"""


class DatabaseMigrationTests(unittest.TestCase):
    def test_price_diagnostic_columns_are_added_without_losing_existing_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old-copytrader.db"
            with closing(sqlite3.connect(path)) as conn:
                conn.executescript(OLD_PAPER_TRADES_SCHEMA)
                conn.execute(
                    """INSERT INTO paper_trades
                    (source_signature, wallet_address, token_mint, side, source_amount,
                    simulated_usd, slippage_bps, delay_seconds, status, price_error)
                    VALUES ('sig-old', 'wallet-old', 'token-old', 'buy', 1, 25, 100,
                    15, 'price_unavailable', 'erro antigo')"""
                )
                conn.commit()

            test_settings = SimpleNamespace(database_path=path)
            with patch.object(database, "settings", test_settings):
                initialize_database()

            with closing(sqlite3.connect(path)) as conn:
                conn.row_factory = sqlite3.Row
                columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(paper_trades)").fetchall()
                }
                row = conn.execute(
                    "SELECT source_signature, status, price_error FROM paper_trades"
                ).fetchone()

        self.assertIn("price_error_code", columns)
        self.assertIn("price_retry_count", columns)
        self.assertIn("last_price_attempt_at", columns)
        self.assertEqual(row["source_signature"], "sig-old")
        self.assertEqual(row["status"], "price_unavailable")
        self.assertEqual(row["price_error"], "erro antigo")

    def test_wave_strategy_version_is_added_without_losing_existing_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old-wave.db"
            with closing(sqlite3.connect(path)) as conn:
                conn.executescript(OLD_WAVE_SIGNALS_SCHEMA)
                conn.execute(
                    """INSERT INTO wave_signals
                    (token_mint, detected_at, wave_score, entry_market_price_usd,
                    entry_execution_price_usd, copy_size_usd, slippage_bps,
                    snapshot_json)
                    VALUES ('old-token', 1000, 50, 1, 1.01, 25, 100, '{}')"""
                )
                conn.commit()

            with patch.object(
                database, "settings", SimpleNamespace(database_path=path)
            ):
                initialize_database()

            with closing(sqlite3.connect(path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT token_mint, strategy_version FROM wave_signals"
                ).fetchone()

        self.assertEqual(row["token_mint"], "old-token")
        self.assertEqual(row["strategy_version"], "wave_v1_baseline")


if __name__ == "__main__":
    unittest.main()
