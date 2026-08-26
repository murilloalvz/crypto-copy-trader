import sqlite3
from contextlib import contextmanager
from pathlib import Path

from src.config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
    address TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_signature TEXT,
    oldest_signature TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    signature TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    block_time INTEGER,
    status TEXT NOT NULL,
    kind TEXT NOT NULL,
    dex TEXT,
    sol_change REAL NOT NULL DEFAULT 0,
    fee_sol REAL NOT NULL DEFAULT 0,
    token_mint TEXT,
    token_change REAL,
    raw_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (wallet_address) REFERENCES wallets(address)
);

CREATE INDEX IF NOT EXISTS idx_transactions_wallet_time
ON transactions(wallet_address, block_time DESC);

CREATE TABLE IF NOT EXISTS paper_trades (
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
    price_error_code TEXT,
    price_retry_count INTEGER NOT NULL DEFAULT 0,
    last_price_attempt_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending_price',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS token_pool_cache (
    token_mint TEXT PRIMARY KEY,
    pool_address TEXT NOT NULL,
    token_side TEXT NOT NULL,
    reserve_usd REAL NOT NULL DEFAULT 0,
    volume_usd_24h REAL NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS price_cache (
    token_mint TEXT NOT NULL,
    minute_ts INTEGER NOT NULL,
    price_usd REAL NOT NULL,
    pool_address TEXT NOT NULL,
    PRIMARY KEY (token_mint, minute_ts)
);

CREATE TABLE IF NOT EXISTS wave_signals (
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

CREATE INDEX IF NOT EXISTS idx_wave_signals_token_time
ON wave_signals(token_mint, detected_at DESC);

CREATE TABLE IF NOT EXISTS wave_signal_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL,
    horizon_minutes INTEGER NOT NULL,
    target_at INTEGER NOT NULL,
    observed_at INTEGER,
    market_price_usd REAL,
    execution_price_usd REAL,
    return_pct REAL,
    pnl_usd REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(signal_id, horizon_minutes),
    FOREIGN KEY (signal_id) REFERENCES wave_signals(id)
);

CREATE INDEX IF NOT EXISTS idx_wave_signal_checks_due
ON wave_signal_checks(status, target_at);
"""


MIGRATIONS = {
    "transactions": {
        "dex": "TEXT",
    },
    "wallets": {
        "oldest_signature": "TEXT",
    },
    "paper_trades": {
        "source_block_time": "INTEGER",
        "market_price_usd": "REAL",
        "execution_price_usd": "REAL",
        "token_quantity": "REAL",
        "fees_usd": "REAL",
        "realized_pnl_usd": "REAL",
        "price_error": "TEXT",
        "price_error_code": "TEXT",
        "price_retry_count": "INTEGER NOT NULL DEFAULT 0",
        "last_price_attempt_at": "TEXT",
    },
    "token_pool_cache": {
        "volume_usd_24h": "REAL NOT NULL DEFAULT 0",
    },
}


def _path() -> Path:
    path = settings.database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connection():
    conn = sqlite3.connect(_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize_database() -> None:
    with connection() as conn:
        conn.executescript(SCHEMA)
        for table, columns in MIGRATIONS.items():
            existing = {
                row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for column, column_type in columns.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def add_wallet(address: str, label: str) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO wallets(address, label) VALUES (?, ?) "
            "ON CONFLICT(address) DO UPDATE SET label=excluded.label, enabled=1",
            (address.strip(), label.strip() or address[:8]),
        )


def remove_wallet(address: str) -> None:
    with connection() as conn:
        conn.execute("UPDATE wallets SET enabled=0 WHERE address=?", (address,))


def rows(query: str, params: tuple = ()) -> list[dict]:
    with connection() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
