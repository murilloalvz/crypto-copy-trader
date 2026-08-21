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
    last_signature TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    signature TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    block_time INTEGER,
    status TEXT NOT NULL,
    kind TEXT NOT NULL,
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
    status TEXT NOT NULL DEFAULT 'simulated',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


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

