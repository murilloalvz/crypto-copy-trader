from __future__ import annotations

import json
from dataclasses import dataclass
import threading

from src import database
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
    slot INTEGER,
    base_amount_raw INTEGER,
    quote_amount_raw INTEGER,
    base_reserves_raw INTEGER,
    quote_reserves_raw INTEGER,
    fee_raw INTEGER,
    fee_basis_points_raw INTEGER,
    creator_fee_raw INTEGER,
    creator_fee_basis_points_raw INTEGER,
    lp_fee_raw INTEGER,
    lp_fee_basis_points_raw INTEGER,
    protocol_fee_raw INTEGER,
    protocol_fee_basis_points_raw INTEGER,
    coin_creator_fee_raw INTEGER,
    coin_creator_fee_basis_points_raw INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(acquisition_run_key, event_key)
);
CREATE INDEX IF NOT EXISTS idx_market_trade_observations_run_token_time
ON market_trade_observations(acquisition_run_key, token_mint, chain_time, observed_at, id);
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
    creator TEXT,
    creation_slot INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(acquisition_run_key, event_key)
);
CREATE INDEX IF NOT EXISTS idx_market_lifecycle_observations_run_token_time
ON market_lifecycle_observations(acquisition_run_key, token_mint, market_started_at, observed_at, id);
CREATE TABLE IF NOT EXISTS market_replay_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acquisition_run_key TEXT NOT NULL,
    event_key TEXT NOT NULL,
    event_type TEXT NOT NULL,
    source_provider TEXT NOT NULL,
    stored_observed_at INTEGER NOT NULL,
    incoming_observed_at INTEGER NOT NULL,
    stored_identity_json TEXT NOT NULL,
    incoming_identity_json TEXT NOT NULL,
    canonical_action TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_market_replay_conflicts_run_event
ON market_replay_conflicts(acquisition_run_key, event_key, id);
"""

_SCHEMA_READY_PATHS: set[str] = set()
_SCHEMA_READY_LOCK = threading.Lock()


def _column_names(conn, table_name: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _database_cache_key() -> str:
    path = database.settings.database_path
    try:
        return str(path.resolve())
    except AttributeError:
        return str(path)


def ensure_market_observation_schema() -> None:
    cache_key = _database_cache_key()
    if cache_key in _SCHEMA_READY_PATHS:
        return
    with _SCHEMA_READY_LOCK:
        if cache_key in _SCHEMA_READY_PATHS:
            return
        with connection() as conn:
            base_schema = _SCHEMA.replace(
                "\nCREATE INDEX IF NOT EXISTS idx_market_trade_observations_run_transaction\nON market_trade_observations(acquisition_run_key, transaction_key, id);\n",
                "\n",
            )
            conn.executescript(base_schema)
            if "transaction_key" not in _column_names(conn, "market_trade_observations"):
                conn.execute("ALTER TABLE market_trade_observations ADD COLUMN transaction_key TEXT")
            if "slot" not in _column_names(conn, "market_trade_observations"):
                conn.execute("ALTER TABLE market_trade_observations ADD COLUMN slot INTEGER")
            for column_name in (
                "base_amount_raw",
                "quote_amount_raw",
                "base_reserves_raw",
                "quote_reserves_raw",
                "fee_raw",
                "fee_basis_points_raw",
                "creator_fee_raw",
                "creator_fee_basis_points_raw",
                "lp_fee_raw",
                "lp_fee_basis_points_raw",
                "protocol_fee_raw",
                "protocol_fee_basis_points_raw",
                "coin_creator_fee_raw",
                "coin_creator_fee_basis_points_raw",
            ):
                if column_name not in _column_names(conn, "market_trade_observations"):
                    conn.execute(
                        f"ALTER TABLE market_trade_observations ADD COLUMN {column_name} INTEGER"
                    )
            if "creator" not in _column_names(conn, "market_lifecycle_observations"):
                conn.execute("ALTER TABLE market_lifecycle_observations ADD COLUMN creator TEXT")
            if "creation_slot" not in _column_names(conn, "market_lifecycle_observations"):
                conn.execute("ALTER TABLE market_lifecycle_observations ADD COLUMN creation_slot INTEGER")
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_market_trade_observations_run_transaction
                ON market_trade_observations(acquisition_run_key, transaction_key, id)"""
            )
        _SCHEMA_READY_PATHS.add(cache_key)


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
    if item.slot is not None and item.slot < 0:
        raise ValueError("slot must be non-negative")
    for field_name in (
        "base_amount_raw",
        "quote_amount_raw",
        "base_reserves_raw",
        "quote_reserves_raw",
        "fee_raw",
        "fee_basis_points_raw",
        "creator_fee_raw",
        "creator_fee_basis_points_raw",
        "lp_fee_raw",
        "lp_fee_basis_points_raw",
        "protocol_fee_raw",
        "protocol_fee_basis_points_raw",
        "coin_creator_fee_raw",
        "coin_creator_fee_basis_points_raw",
    ):
        value = getattr(item, field_name)
        if value is not None and value < 0:
            raise ValueError(f"{field_name} must be non-negative")


def _validate_lifecycle(item: MarketLifecycleObservation) -> None:
    _required(item.token_mint, "token_mint")
    if item.market_started_at < 0 or item.observed_at < 0:
        raise ValueError("lifecycle timestamps must be non-negative")
    if item.venue is not None and not item.venue.strip():
        raise ValueError("venue cannot be blank")
    if item.creator is not None and not item.creator.strip():
        raise ValueError("creator cannot be blank")
    if item.creation_slot is not None and item.creation_slot < 0:
        raise ValueError("creation_slot must be non-negative")


def _identity_sort_key(identity: tuple) -> str:
    return json.dumps(identity, separators=(",", ":"), ensure_ascii=True)


def _choose_conflict_action(*, stored_observed_at: int, incoming_observed_at: int, stored_identity: tuple, incoming_identity: tuple) -> tuple[str, bool]:
    if incoming_observed_at < stored_observed_at:
        return "replace_with_earlier_observation", True
    if incoming_observed_at > stored_observed_at:
        return "retain_earlier_observation", False
    if _identity_sort_key(incoming_identity) < _identity_sort_key(stored_identity):
        return "replace_equal_timestamp_by_identity_order", True
    return "retain_equal_timestamp_by_identity_order", False


def _record_replay_conflict(conn, *, acquisition_run_key: str, event_key: str, event_type: str, source_provider: str, stored_observed_at: int, incoming_observed_at: int, stored_identity: tuple, incoming_identity: tuple, canonical_action: str) -> None:
    conn.execute(
        """INSERT INTO market_replay_conflicts(
            acquisition_run_key, event_key, event_type, source_provider,
            stored_observed_at, incoming_observed_at,
            stored_identity_json, incoming_identity_json, canonical_action
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            acquisition_run_key,
            event_key,
            event_type,
            source_provider,
            int(stored_observed_at),
            int(incoming_observed_at),
            _identity_sort_key(stored_identity),
            _identity_sort_key(incoming_identity),
            canonical_action,
        ),
    )


def record_market_trade(*, acquisition_run_key: str, event_key: str, source_provider: str, observation: MarketTradeObservation) -> bool:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    raw_key = _required(event_key, "event_key")
    provider = _required(source_provider, "source_provider")
    _validate_trade(observation)
    ensure_market_observation_schema()
    identity_values = (
        provider,
        observation.token_mint,
        observation.side,
        observation.chain_time,
        observation.wallet_address,
        observation.notional_usd,
        observation.price_usd,
        observation.venue,
        observation.transaction_key,
        observation.slot,
        observation.base_amount_raw,
        observation.quote_amount_raw,
        observation.base_reserves_raw,
        observation.quote_reserves_raw,
        observation.fee_raw,
        observation.fee_basis_points_raw,
        observation.creator_fee_raw,
        observation.creator_fee_basis_points_raw,
        observation.lp_fee_raw,
        observation.lp_fee_basis_points_raw,
        observation.protocol_fee_raw,
        observation.protocol_fee_basis_points_raw,
        observation.coin_creator_fee_raw,
        observation.coin_creator_fee_basis_points_raw,
    )
    with connection() as conn:
        existing = conn.execute(
            """SELECT source_provider, token_mint, side, chain_time, observed_at,
                wallet_address, notional_usd, price_usd, venue, transaction_key, slot,
                base_amount_raw, quote_amount_raw, base_reserves_raw, quote_reserves_raw,
                fee_raw, fee_basis_points_raw, creator_fee_raw, creator_fee_basis_points_raw,
                lp_fee_raw, lp_fee_basis_points_raw, protocol_fee_raw, protocol_fee_basis_points_raw,
                coin_creator_fee_raw, coin_creator_fee_basis_points_raw
            FROM market_trade_observations
            WHERE acquisition_run_key=? AND event_key=?""",
            (run_key, raw_key),
        ).fetchone()
        if existing is not None:
            existing_identity = tuple(existing[key] for key in (
                "source_provider", "token_mint", "side", "chain_time",
                "wallet_address", "notional_usd", "price_usd", "venue", "transaction_key", "slot",
                "base_amount_raw", "quote_amount_raw", "base_reserves_raw", "quote_reserves_raw",
                "fee_raw", "fee_basis_points_raw", "creator_fee_raw", "creator_fee_basis_points_raw",
                "lp_fee_raw", "lp_fee_basis_points_raw", "protocol_fee_raw", "protocol_fee_basis_points_raw",
                "coin_creator_fee_raw", "coin_creator_fee_basis_points_raw",
            ))
            stored_observed_at = int(existing["observed_at"])
            incoming_observed_at = int(observation.observed_at)
            if existing_identity == identity_values:
                if incoming_observed_at < stored_observed_at:
                    conn.execute(
                        "UPDATE market_trade_observations SET observed_at=? WHERE acquisition_run_key=? AND event_key=?",
                        (incoming_observed_at, run_key, raw_key),
                    )
                return False
            action, incoming_wins = _choose_conflict_action(
                stored_observed_at=stored_observed_at,
                incoming_observed_at=incoming_observed_at,
                stored_identity=existing_identity,
                incoming_identity=identity_values,
            )
            _record_replay_conflict(
                conn,
                acquisition_run_key=run_key,
                event_key=raw_key,
                event_type="trade",
                source_provider=provider,
                stored_observed_at=stored_observed_at,
                incoming_observed_at=incoming_observed_at,
                stored_identity=existing_identity,
                incoming_identity=identity_values,
                canonical_action=action,
            )
            if incoming_wins:
                conn.execute(
                    """UPDATE market_trade_observations
                    SET source_provider=?, token_mint=?, side=?, chain_time=?, observed_at=?,
                        wallet_address=?, notional_usd=?, price_usd=?, venue=?, transaction_key=?,
                        slot=?, base_amount_raw=?, quote_amount_raw=?,
                        base_reserves_raw=?, quote_reserves_raw=?,
                        fee_raw=?, fee_basis_points_raw=?, creator_fee_raw=?, creator_fee_basis_points_raw=?,
                        lp_fee_raw=?, lp_fee_basis_points_raw=?, protocol_fee_raw=?, protocol_fee_basis_points_raw=?,
                        coin_creator_fee_raw=?, coin_creator_fee_basis_points_raw=?
                    WHERE acquisition_run_key=? AND event_key=?""",
                    (
                        provider, observation.token_mint, observation.side, observation.chain_time,
                        incoming_observed_at, observation.wallet_address, observation.notional_usd,
                        observation.price_usd, observation.venue, observation.transaction_key,
                        observation.slot, observation.base_amount_raw, observation.quote_amount_raw,
                        observation.base_reserves_raw, observation.quote_reserves_raw,
                        observation.fee_raw, observation.fee_basis_points_raw,
                        observation.creator_fee_raw, observation.creator_fee_basis_points_raw,
                        observation.lp_fee_raw, observation.lp_fee_basis_points_raw,
                        observation.protocol_fee_raw, observation.protocol_fee_basis_points_raw,
                        observation.coin_creator_fee_raw, observation.coin_creator_fee_basis_points_raw,
                        run_key, raw_key,
                    ),
                )
            return False
        conn.execute(
            """INSERT INTO market_trade_observations(
                acquisition_run_key, event_key, source_provider, token_mint, side,
                chain_time, observed_at, wallet_address, notional_usd, price_usd, venue,
                transaction_key, slot, base_amount_raw, quote_amount_raw,
                base_reserves_raw, quote_reserves_raw,
                fee_raw, fee_basis_points_raw, creator_fee_raw, creator_fee_basis_points_raw,
                lp_fee_raw, lp_fee_basis_points_raw, protocol_fee_raw, protocol_fee_basis_points_raw,
                coin_creator_fee_raw, coin_creator_fee_basis_points_raw
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_key, raw_key, provider, observation.token_mint, observation.side,
                observation.chain_time, observation.observed_at, observation.wallet_address,
                observation.notional_usd, observation.price_usd, observation.venue,
                observation.transaction_key, observation.slot, observation.base_amount_raw,
                observation.quote_amount_raw, observation.base_reserves_raw,
                observation.quote_reserves_raw,
                observation.fee_raw, observation.fee_basis_points_raw,
                observation.creator_fee_raw, observation.creator_fee_basis_points_raw,
                observation.lp_fee_raw, observation.lp_fee_basis_points_raw,
                observation.protocol_fee_raw, observation.protocol_fee_basis_points_raw,
                observation.coin_creator_fee_raw, observation.coin_creator_fee_basis_points_raw,
            ),
        )
        return True


def record_market_lifecycle(*, acquisition_run_key: str, event_key: str, source_provider: str, observation: MarketLifecycleObservation) -> bool:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    raw_key = _required(event_key, "event_key")
    provider = _required(source_provider, "source_provider")
    _validate_lifecycle(observation)
    ensure_market_observation_schema()
    identity_values = (
        provider, observation.token_mint, observation.market_started_at, observation.venue,
        observation.creator, observation.creation_slot,
    )
    with connection() as conn:
        existing = conn.execute(
            """SELECT source_provider, token_mint, market_started_at, observed_at, venue,
                creator, creation_slot
            FROM market_lifecycle_observations
            WHERE acquisition_run_key=? AND event_key=?""",
            (run_key, raw_key),
        ).fetchone()
        if existing is not None:
            existing_identity = tuple(existing[key] for key in (
                "source_provider", "token_mint", "market_started_at", "venue",
                "creator", "creation_slot",
            ))
            stored_observed_at = int(existing["observed_at"])
            incoming_observed_at = int(observation.observed_at)
            if existing_identity == identity_values:
                if incoming_observed_at < stored_observed_at:
                    conn.execute(
                        "UPDATE market_lifecycle_observations SET observed_at=? WHERE acquisition_run_key=? AND event_key=?",
                        (incoming_observed_at, run_key, raw_key),
                    )
                return False
            action, incoming_wins = _choose_conflict_action(
                stored_observed_at=stored_observed_at,
                incoming_observed_at=incoming_observed_at,
                stored_identity=existing_identity,
                incoming_identity=identity_values,
            )
            _record_replay_conflict(
                conn,
                acquisition_run_key=run_key,
                event_key=raw_key,
                event_type="lifecycle",
                source_provider=provider,
                stored_observed_at=stored_observed_at,
                incoming_observed_at=incoming_observed_at,
                stored_identity=existing_identity,
                incoming_identity=identity_values,
                canonical_action=action,
            )
            if incoming_wins:
                conn.execute(
                    """UPDATE market_lifecycle_observations
                    SET source_provider=?, token_mint=?, market_started_at=?, observed_at=?, venue=?,
                        creator=?, creation_slot=?
                    WHERE acquisition_run_key=? AND event_key=?""",
                    (
                        provider, observation.token_mint, observation.market_started_at,
                        incoming_observed_at, observation.venue, observation.creator,
                        observation.creation_slot, run_key, raw_key,
                    ),
                )
            return False
        conn.execute(
            """INSERT INTO market_lifecycle_observations(
                acquisition_run_key, event_key, source_provider, token_mint,
                market_started_at, observed_at, venue, creator, creation_slot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_key, raw_key, provider, observation.token_mint,
                observation.market_started_at, observation.observed_at, observation.venue,
                observation.creator, observation.creation_slot,
            ),
        )
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
        transaction_key, slot, base_amount_raw, quote_amount_raw,
        base_reserves_raw, quote_reserves_raw,
        fee_raw, fee_basis_points_raw, creator_fee_raw, creator_fee_basis_points_raw,
        lp_fee_raw, lp_fee_basis_points_raw, protocol_fee_raw, protocol_fee_basis_points_raw,
        coin_creator_fee_raw, coin_creator_fee_basis_points_raw
        FROM market_trade_observations
        WHERE acquisition_run_key=? AND token_mint=?"""
    params: list[object] = [run_key, mint]
    if as_of is not None:
        query += " AND observed_at<=?"
        params.append(as_of)
    if chain_time_after is not None:
        query += " AND chain_time>?"
        params.append(chain_time_after)
    query += " ORDER BY chain_time, observed_at, id"
    with connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return tuple(
        StoredMarketTrade(
            acquisition_run_key=str(row["acquisition_run_key"]),
            event_key=str(row["event_key"]),
            source_provider=str(row["source_provider"]),
            observation=MarketTradeObservation(
                token_mint=str(row["token_mint"]),
                side=str(row["side"]),
                chain_time=int(row["chain_time"]),
                observed_at=int(row["observed_at"]),
                wallet_address=(str(row["wallet_address"]) if row["wallet_address"] is not None else None),
                notional_usd=(float(row["notional_usd"]) if row["notional_usd"] is not None else None),
                price_usd=(float(row["price_usd"]) if row["price_usd"] is not None else None),
                venue=(str(row["venue"]) if row["venue"] is not None else None),
                transaction_key=(str(row["transaction_key"]) if row["transaction_key"] is not None else None),
                slot=(int(row["slot"]) if row["slot"] is not None else None),
                base_amount_raw=(int(row["base_amount_raw"]) if row["base_amount_raw"] is not None else None),
                quote_amount_raw=(int(row["quote_amount_raw"]) if row["quote_amount_raw"] is not None else None),
                base_reserves_raw=(int(row["base_reserves_raw"]) if row["base_reserves_raw"] is not None else None),
                quote_reserves_raw=(int(row["quote_reserves_raw"]) if row["quote_reserves_raw"] is not None else None),
                fee_raw=(int(row["fee_raw"]) if row["fee_raw"] is not None else None),
                fee_basis_points_raw=(int(row["fee_basis_points_raw"]) if row["fee_basis_points_raw"] is not None else None),
                creator_fee_raw=(int(row["creator_fee_raw"]) if row["creator_fee_raw"] is not None else None),
                creator_fee_basis_points_raw=(int(row["creator_fee_basis_points_raw"]) if row["creator_fee_basis_points_raw"] is not None else None),
                lp_fee_raw=(int(row["lp_fee_raw"]) if row["lp_fee_raw"] is not None else None),
                lp_fee_basis_points_raw=(int(row["lp_fee_basis_points_raw"]) if row["lp_fee_basis_points_raw"] is not None else None),
                protocol_fee_raw=(int(row["protocol_fee_raw"]) if row["protocol_fee_raw"] is not None else None),
                protocol_fee_basis_points_raw=(int(row["protocol_fee_basis_points_raw"]) if row["protocol_fee_basis_points_raw"] is not None else None),
                coin_creator_fee_raw=(int(row["coin_creator_fee_raw"]) if row["coin_creator_fee_raw"] is not None else None),
                coin_creator_fee_basis_points_raw=(int(row["coin_creator_fee_basis_points_raw"]) if row["coin_creator_fee_basis_points_raw"] is not None else None),
            ),
        )
        for row in rows
    )


def load_latest_market_lifecycle(*, acquisition_run_key: str, token_mint: str, as_of: int | None = None, venue: str | None = None) -> StoredMarketLifecycle | None:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    mint = _required(token_mint, "token_mint")
    if as_of is not None and as_of < 0:
        raise ValueError("as_of must be non-negative")
    normalized_venue = _required(venue, "venue") if venue is not None else None
    ensure_market_observation_schema()
    query = """SELECT acquisition_run_key, event_key, source_provider, token_mint,
        market_started_at, observed_at, venue, creator, creation_slot
        FROM market_lifecycle_observations
        WHERE acquisition_run_key=? AND token_mint=?"""
    params: list[object] = [run_key, mint]
    if as_of is not None:
        query += " AND observed_at<=?"
        params.append(as_of)
    if normalized_venue is not None:
        query += " AND venue=?"
        params.append(normalized_venue)
    query += " ORDER BY observed_at DESC, id DESC LIMIT 1"
    with connection() as conn:
        row = conn.execute(query, tuple(params)).fetchone()
    if row is None:
        return None
    return StoredMarketLifecycle(
        acquisition_run_key=str(row["acquisition_run_key"]),
        event_key=str(row["event_key"]),
        source_provider=str(row["source_provider"]),
        observation=MarketLifecycleObservation(
            token_mint=str(row["token_mint"]),
            market_started_at=int(row["market_started_at"]),
            observed_at=int(row["observed_at"]),
            venue=(str(row["venue"]) if row["venue"] is not None else None),
            creator=(str(row["creator"]) if row["creator"] is not None else None),
            creation_slot=(int(row["creation_slot"]) if row["creation_slot"] is not None else None),
        ),
    )


def count_market_replay_conflicts(*, acquisition_run_key: str) -> int:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    ensure_market_observation_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM market_replay_conflicts WHERE acquisition_run_key=?",
            (run_key,),
        ).fetchone()
    return int(row["n"])
