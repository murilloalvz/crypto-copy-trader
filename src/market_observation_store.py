from dataclasses import dataclass

from src.database import connection
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation


@dataclass(frozen=True)
class StoredMarketTrade:
    acquisition_run_key: str
    event_key: str
    source_provider: str
    observation: MarketTradeObservation


@dataclass(frozen=True)
class StoredMarketLifecycle:
    acquisition_run_key: str
    event_key: str
    source_provider: str
    observation: MarketLifecycleObservation


_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_trade_observations (
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
);

CREATE INDEX IF NOT EXISTS idx_market_trade_observations_run_token_time
ON market_trade_observations(
    acquisition_run_key, token_mint, chain_time, observed_at, id
);

CREATE INDEX IF NOT EXISTS idx_market_trade_observations_run_transaction
ON market_trade_observations(acquisition_run_key, transaction_key, id);

CREATE TABLE IF NOT EXISTS market_lifecycle_observations (
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
);

CREATE INDEX IF NOT EXISTS idx_market_lifecycle_observations_run_token_time
ON market_lifecycle_observations(
    acquisition_run_key, token_mint, market_started_at, observed_at, id
);
"""


def _column_names(conn, table_name: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def ensure_market_observation_schema() -> None:
    with connection() as conn:
        base_schema = _SCHEMA.replace(
            "\nCREATE INDEX IF NOT EXISTS idx_market_trade_observations_run_transaction\nON market_trade_observations(acquisition_run_key, transaction_key, id);\n",
            "\n",
        )
        conn.executescript(base_schema)
        if "transaction_key" not in _column_names(conn, "market_trade_observations"):
            conn.execute("ALTER TABLE market_trade_observations ADD COLUMN transaction_key TEXT")
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_market_trade_observations_run_transaction
            ON market_trade_observations(acquisition_run_key, transaction_key, id)"""
        )


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _validate_trade(item: MarketTradeObservation) -> None:
    _required(item.token_mint, "token_mint")
    if item.side not in {"buy", "sell"}:
        raise ValueError("trade side must be buy or sell")
    if item.chain_time < 0 or item.observed_at < 0:
        raise ValueError("trade timestamps must be non-negative")
    if item.observed_at < item.chain_time:
        raise ValueError("trade observed_at cannot precede chain_time")
    if item.wallet_address is not None and not item.wallet_address.strip():
        raise ValueError("wallet_address cannot be blank")
    if item.venue is not None and not item.venue.strip():
        raise ValueError("venue cannot be blank")
    if item.transaction_key is not None and not item.transaction_key.strip():
        raise ValueError("transaction_key cannot be blank")
    if item.notional_usd is not None and item.notional_usd < 0:
        raise ValueError("notional_usd must be non-negative")
    if item.price_usd is not None and item.price_usd <= 0:
        raise ValueError("price_usd must be positive")


def _validate_lifecycle(item: MarketLifecycleObservation) -> None:
    _required(item.token_mint, "token_mint")
    if item.market_started_at < 0 or item.observed_at < 0:
        raise ValueError("lifecycle timestamps must be non-negative")
    if item.observed_at < item.market_started_at:
        raise ValueError("lifecycle observed_at cannot precede market_started_at")
    if item.venue is not None and not item.venue.strip():
        raise ValueError("venue cannot be blank")


def record_market_trade(*, acquisition_run_key: str, event_key: str, source_provider: str, observation: MarketTradeObservation) -> bool:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    raw_key = _required(event_key, "event_key")
    provider = _required(source_provider, "source_provider")
    _validate_trade(observation)
    ensure_market_observation_schema()
    identity_values = (provider, observation.token_mint, observation.side, observation.chain_time, observation.wallet_address, observation.notional_usd, observation.price_usd, observation.venue, observation.transaction_key)
    with connection() as conn:
        existing = conn.execute(
            """SELECT source_provider, token_mint, side, chain_time, observed_at,
                wallet_address, notional_usd, price_usd, venue, transaction_key
            FROM market_trade_observations
            WHERE acquisition_run_key=? AND event_key=?""", (run_key, raw_key)).fetchone()
        if existing is not None:
            existing_identity = tuple(existing[key] for key in ("source_provider", "token_mint", "side", "chain_time", "wallet_address", "notional_usd", "price_usd", "venue", "transaction_key"))
            if existing_identity != identity_values:
                raise ValueError("market trade event already exists with different data")
            first_observed_at = int(existing["observed_at"])
            if observation.observed_at < first_observed_at:
                raise ValueError("market trade replay observed_at precedes first observation")
            return False
        conn.execute(
            """INSERT INTO market_trade_observations(
                acquisition_run_key, event_key, source_provider, token_mint, side,
                chain_time, observed_at, wallet_address, notional_usd, price_usd, venue,
                transaction_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_key, raw_key, provider, observation.token_mint, observation.side, observation.chain_time, observation.observed_at, observation.wallet_address, observation.notional_usd, observation.price_usd, observation.venue, observation.transaction_key))
        return True


def record_market_lifecycle(*, acquisition_run_key: str, event_key: str, source_provider: str, observation: MarketLifecycleObservation) -> bool:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    raw_key = _required(event_key, "event_key")
    provider = _required(source_provider, "source_provider")
    _validate_lifecycle(observation)
    ensure_market_observation_schema()
    identity_values = (provider, observation.token_mint, observation.market_started_at, observation.venue)
    with connection() as conn:
        existing = conn.execute(
            """SELECT source_provider, token_mint, market_started_at, observed_at, venue
            FROM market_lifecycle_observations
            WHERE acquisition_run_key=? AND event_key=?""", (run_key, raw_key)).fetchone()
        if existing is not None:
            existing_identity = tuple(existing[key] for key in ("source_provider", "token_mint", "market_started_at", "venue"))
            if existing_identity != identity_values:
                raise ValueError("market lifecycle event already exists with different data")
            first_observed_at = int(existing["observed_at"])
            if observation.observed_at < first_observed_at:
                raise ValueError("market lifecycle replay observed_at precedes first observation")
            return False
        conn.execute(
            """INSERT INTO market_lifecycle_observations(
                acquisition_run_key, event_key, source_provider, token_mint,
                market_started_at, observed_at, venue
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_key, raw_key, provider, observation.token_mint, observation.market_started_at, observation.observed_at, observation.venue))
        return True


def load_market_trades(*, acquisition_run_key: str, token_mint: str, as_of: int | None = None, chain_time_after: int | None = None) -> tuple[StoredMarketTrade, ...]:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    mint = _required(token_mint, "token_mint")
    if as_of is not None and as_of < 0:
        raise ValueError("as_of must be non-negative")
    if chain_time_after is not None and chain_time_after < 0:
        raise ValueError("chain_time_after must be non-negative")
    ensure_market_observation_schema()
    query = """SELECT acquisition_run_key, event_key, source_provider, token_mint, side,
        chain_time, observed_at, wallet_address, notional_usd, price_usd, venue,
        transaction_key FROM market_trade_observations
        WHERE acquisition_run_key=? AND token_mint=?"""
    params: list[object] = [run_key, mint]
    if as_of is not None:
        query += " AND observed_at<=?"; params.append(as_of)
    if chain_time_after is not None:
        query += " AND chain_time>?"; params.append(chain_time_after)
    query += " ORDER BY chain_time, observed_at, id"
    with connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return tuple(StoredMarketTrade(acquisition_run_key=str(row["acquisition_run_key"]), event_key=str(row["event_key"]), source_provider=str(row["source_provider"]), observation=MarketTradeObservation(token_mint=str(row["token_mint"]), side=str(row["side"]), chain_time=int(row["chain_time"]), observed_at=int(row["observed_at"]), wallet_address=(str(row["wallet_address"]) if row["wallet_address"] is not None else None), notional_usd=(float(row["notional_usd"]) if row["notional_usd"] is not None else None), price_usd=(float(row["price_usd"]) if row["price_usd"] is not None else None), venue=(str(row["venue"]) if row["venue"] is not None else None), transaction_key=(str(row["transaction_key"]) if row["transaction_key"] is not None else None))) for row in rows)


def load_latest_market_lifecycle(*, acquisition_run_key: str, token_mint: str, as_of: int | None = None, venue: str | None = None) -> StoredMarketLifecycle | None:
    """Load the latest causally available lifecycle row, optionally restricted to one venue.

    Venue filtering is important in a unified stream: Pump bonding ``CreateEvent`` represents token
    birth for the fresh-market branch, while PumpSwap ``CreatePoolEvent`` represents pool/venue
    lifecycle and must not redefine token age.
    """
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    mint = _required(token_mint, "token_mint")
    if as_of is not None and as_of < 0:
        raise ValueError("as_of must be non-negative")
    normalized_venue = _required(venue, "venue") if venue is not None else None
    ensure_market_observation_schema()
    query = """SELECT acquisition_run_key, event_key, source_provider, token_mint,
        market_started_at, observed_at, venue FROM market_lifecycle_observations
        WHERE acquisition_run_key=? AND token_mint=?"""
    params: list[object] = [run_key, mint]
    if as_of is not None:
        query += " AND observed_at<=?"; params.append(as_of)
    if normalized_venue is not None:
        query += " AND venue=?"; params.append(normalized_venue)
    query += " ORDER BY observed_at DESC, id DESC LIMIT 1"
    with connection() as conn:
        row = conn.execute(query, tuple(params)).fetchone()
    if row is None:
        return None
    return StoredMarketLifecycle(acquisition_run_key=str(row["acquisition_run_key"]), event_key=str(row["event_key"]), source_provider=str(row["source_provider"]), observation=MarketLifecycleObservation(token_mint=str(row["token_mint"]), market_started_at=int(row["market_started_at"]), observed_at=int(row["observed_at"]), venue=(str(row["venue"]) if row["venue"] is not None else None)))
