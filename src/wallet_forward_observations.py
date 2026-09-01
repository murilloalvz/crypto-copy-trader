from src.database import connection
from src.opportunity_intelligence import WalletActionObservation


_SCHEMA = """
CREATE TABLE IF NOT EXISTS wallet_forward_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_key TEXT NOT NULL UNIQUE,
    wallet_address TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    side TEXT NOT NULL,
    chain_time INTEGER NOT NULL,
    observed_at INTEGER NOT NULL,
    signature TEXT,
    dex TEXT,
    source TEXT NOT NULL DEFAULT 'solana_rpc_forward',
    run_key TEXT,
    token_delta_raw TEXT,
    token_decimals INTEGER,
    token_balance_before_raw TEXT,
    token_balance_after_raw TEXT,
    token_quantity_flags TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wallet_forward_token_time
ON wallet_forward_observations(token_mint, observed_at);

CREATE INDEX IF NOT EXISTS idx_wallet_forward_wallet_time
ON wallet_forward_observations(wallet_address, observed_at);

"""


def ensure_wallet_forward_observation_schema() -> None:
    with connection() as conn:
        conn.executescript(_SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(wallet_forward_observations)")}
        if "run_key" not in columns:
            conn.execute("ALTER TABLE wallet_forward_observations ADD COLUMN run_key TEXT")
        for name, sql_type in (("token_delta_raw", "TEXT"), ("token_decimals", "INTEGER"), ("token_balance_before_raw", "TEXT"), ("token_balance_after_raw", "TEXT"), ("token_quantity_flags", "TEXT")):
            if name not in columns:
                conn.execute(f"ALTER TABLE wallet_forward_observations ADD COLUMN {name} {sql_type}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wallet_forward_run_id ON wallet_forward_observations(run_key, id)")


def _validate(observation: WalletActionObservation, observation_key: str) -> None:
    if not observation_key.strip():
        raise ValueError("observation_key cannot be empty")
    if not observation.address.strip():
        raise ValueError("wallet address cannot be empty")
    if not observation.token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    if observation.side not in {"buy", "sell"}:
        raise ValueError("wallet side must be buy or sell")
    if observation.chain_time < 0 or observation.observed_at < 0:
        raise ValueError("wallet timestamps must be non-negative")
    if observation.observed_at < observation.chain_time:
        raise ValueError("observed_at cannot be earlier than chain_time")


def record_wallet_forward_observation(
    observation: WalletActionObservation,
    *,
    observation_key: str,
    signature: str | None = None,
    dex: str | None = None,
    source: str = "solana_rpc_forward",
    run_key: str | None = None,
    token_delta_raw: str | None = None,
    token_decimals: int | None = None,
    token_balance_before_raw: str | None = None,
    token_balance_after_raw: str | None = None,
    token_quantity_flags: str | None = None,
) -> bool:
    """Persist one action exactly once and return whether a new row was inserted."""
    _validate(observation, observation_key)
    if not source.strip():
        raise ValueError("source cannot be empty")
    ensure_wallet_forward_observation_schema()
    with connection() as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO wallet_forward_observations(
                observation_key, wallet_address, token_mint, side,
                chain_time, observed_at, signature, dex, source, run_key,
                token_delta_raw, token_decimals, token_balance_before_raw, token_balance_after_raw
                , token_quantity_flags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                observation_key.strip(),
                observation.address.strip(),
                observation.token_mint.strip(),
                observation.side,
                observation.chain_time,
                observation.observed_at,
                signature,
                dex,
                source.strip(),
                run_key.strip() if run_key else None,
                str(token_delta_raw) if token_delta_raw is not None else None,
                token_decimals,
                str(token_balance_before_raw) if token_balance_before_raw is not None else None,
                str(token_balance_after_raw) if token_balance_after_raw is not None else None,
                token_quantity_flags,
            ),
        )
        return cursor.rowcount == 1


def load_wallet_forward_observations(
    *,
    token_mint: str,
    as_of: int | None = None,
) -> list[WalletActionObservation]:
    if not token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    if as_of is not None and as_of < 0:
        raise ValueError("as_of must be non-negative")

    ensure_wallet_forward_observation_schema()
    query = """SELECT wallet_address, token_mint, side, chain_time, observed_at
        FROM wallet_forward_observations
        WHERE token_mint=?"""
    params: tuple = (token_mint.strip(),)
    if as_of is not None:
        query += " AND observed_at<=?"
        params = (token_mint.strip(), as_of)
    query += " ORDER BY observed_at, id"

    with connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        WalletActionObservation(
            address=str(row["wallet_address"]),
            token_mint=str(row["token_mint"]),
            side=str(row["side"]),
            chain_time=int(row["chain_time"]),
            observed_at=int(row["observed_at"]),
        )
        for row in rows
    ]
