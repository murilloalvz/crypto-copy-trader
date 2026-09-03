from dataclasses import dataclass
import json
import threading

from src import database
from src.database import connection


@dataclass(frozen=True)
class PumpSwapPoolMapping:
    acquisition_run_key: str
    pool_address: str
    base_mint: str
    quote_mint: str
    observed_at: int
    source_provider: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS pumpswap_pool_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acquisition_run_key TEXT NOT NULL,
    pool_address TEXT NOT NULL,
    base_mint TEXT NOT NULL,
    quote_mint TEXT NOT NULL,
    observed_at INTEGER NOT NULL,
    source_provider TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(acquisition_run_key, pool_address)
);

CREATE INDEX IF NOT EXISTS idx_pumpswap_pool_mappings_run_pool_time
ON pumpswap_pool_mappings(acquisition_run_key, pool_address, observed_at, id);

CREATE INDEX IF NOT EXISTS idx_pumpswap_pool_mappings_pool_time
ON pumpswap_pool_mappings(pool_address, observed_at, id);

CREATE TABLE IF NOT EXISTS pumpswap_pool_mapping_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acquisition_run_key TEXT NOT NULL,
    pool_address TEXT NOT NULL,
    stored_observed_at INTEGER NOT NULL,
    incoming_observed_at INTEGER NOT NULL,
    stored_identity_json TEXT NOT NULL,
    incoming_identity_json TEXT NOT NULL,
    stored_source_provider TEXT NOT NULL,
    incoming_source_provider TEXT NOT NULL,
    canonical_action TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pumpswap_pool_mapping_conflicts_run
ON pumpswap_pool_mapping_conflicts(acquisition_run_key, pool_address, id);
"""

_SCHEMA_READY_PATHS: set[str] = set()
_SCHEMA_READY_LOCK = threading.Lock()


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _database_cache_key() -> str:
    path = database.settings.database_path
    try:
        return str(path.resolve())
    except AttributeError:
        return str(path)


def _row_to_mapping(row) -> PumpSwapPoolMapping:
    return PumpSwapPoolMapping(
        acquisition_run_key=str(row["acquisition_run_key"]),
        pool_address=str(row["pool_address"]),
        base_mint=str(row["base_mint"]),
        quote_mint=str(row["quote_mint"]),
        observed_at=int(row["observed_at"]),
        source_provider=str(row["source_provider"]),
    )


def ensure_pumpswap_pool_schema() -> None:
    cache_key = _database_cache_key()
    if cache_key in _SCHEMA_READY_PATHS:
        return
    with _SCHEMA_READY_LOCK:
        if cache_key in _SCHEMA_READY_PATHS:
            return
        with connection() as conn:
            conn.executescript(_SCHEMA)
        _SCHEMA_READY_PATHS.add(cache_key)


def _identity_key(base_mint: str, quote_mint: str) -> str:
    return json.dumps((base_mint, quote_mint), separators=(",", ":"))


def _record_conflict(
    conn,
    *,
    acquisition_run_key: str,
    pool_address: str,
    stored_observed_at: int,
    incoming_observed_at: int,
    stored_identity: tuple[str, str],
    incoming_identity: tuple[str, str],
    stored_source_provider: str,
    incoming_source_provider: str,
    canonical_action: str,
) -> None:
    conn.execute(
        """INSERT INTO pumpswap_pool_mapping_conflicts(
            acquisition_run_key, pool_address,
            stored_observed_at, incoming_observed_at,
            stored_identity_json, incoming_identity_json,
            stored_source_provider, incoming_source_provider, canonical_action
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            acquisition_run_key,
            pool_address,
            int(stored_observed_at),
            int(incoming_observed_at),
            _identity_key(*stored_identity),
            _identity_key(*incoming_identity),
            stored_source_provider,
            incoming_source_provider,
            canonical_action,
        ),
    )


def record_pumpswap_pool_mapping(
    *,
    acquisition_run_key: str,
    pool_address: str,
    base_mint: str,
    quote_mint: str,
    observed_at: int,
    source_provider: str,
) -> bool:
    """Persist immutable PumpSwap pool identity with causal replay semantics.

    Concurrent workers can learn the same pool through RPC and CreatePoolEvent in a different
    completion order. The earliest observation wins; equal-time identity conflicts use a stable
    lexical tie-break. Conflicts remain auditable instead of aborting the whole acquisition run.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    pool = _required(pool_address, "pool_address")
    base = _required(base_mint, "base_mint")
    quote = _required(quote_mint, "quote_mint")
    provider = _required(source_provider, "source_provider")
    learned_at = int(observed_at)
    if learned_at < 0:
        raise ValueError("observed_at must be non-negative")
    ensure_pumpswap_pool_schema()

    incoming_identity = (base, quote)
    with connection() as conn:
        existing = conn.execute(
            """SELECT base_mint, quote_mint, observed_at, source_provider
            FROM pumpswap_pool_mappings
            WHERE acquisition_run_key=? AND pool_address=?""",
            (run_key, pool),
        ).fetchone()
        if existing is not None:
            stored_identity = (str(existing["base_mint"]), str(existing["quote_mint"]))
            stored_observed_at = int(existing["observed_at"])
            stored_provider = str(existing["source_provider"])

            if stored_identity == incoming_identity:
                if learned_at < stored_observed_at:
                    conn.execute(
                        """UPDATE pumpswap_pool_mappings
                        SET observed_at=?, source_provider=?
                        WHERE acquisition_run_key=? AND pool_address=?""",
                        (learned_at, provider, run_key, pool),
                    )
                return False

            incoming_wins = (
                learned_at < stored_observed_at
                or (
                    learned_at == stored_observed_at
                    and _identity_key(*incoming_identity) < _identity_key(*stored_identity)
                )
            )
            action = "replace_with_canonical_mapping" if incoming_wins else "retain_canonical_mapping"
            _record_conflict(
                conn,
                acquisition_run_key=run_key,
                pool_address=pool,
                stored_observed_at=stored_observed_at,
                incoming_observed_at=learned_at,
                stored_identity=stored_identity,
                incoming_identity=incoming_identity,
                stored_source_provider=stored_provider,
                incoming_source_provider=provider,
                canonical_action=action,
            )
            if incoming_wins:
                conn.execute(
                    """UPDATE pumpswap_pool_mappings
                    SET base_mint=?, quote_mint=?, observed_at=?, source_provider=?
                    WHERE acquisition_run_key=? AND pool_address=?""",
                    (base, quote, learned_at, provider, run_key, pool),
                )
            return False

        conn.execute(
            """INSERT INTO pumpswap_pool_mappings(
                acquisition_run_key, pool_address, base_mint, quote_mint,
                observed_at, source_provider
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (run_key, pool, base, quote, learned_at, provider),
        )
        return True


def load_pumpswap_pool_mapping(
    *,
    acquisition_run_key: str,
    pool_address: str,
    as_of: int | None = None,
) -> PumpSwapPoolMapping | None:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    pool = _required(pool_address, "pool_address")
    if as_of is not None and int(as_of) < 0:
        raise ValueError("as_of must be non-negative")
    ensure_pumpswap_pool_schema()

    query = """SELECT acquisition_run_key, pool_address, base_mint, quote_mint,
        observed_at, source_provider
        FROM pumpswap_pool_mappings
        WHERE acquisition_run_key=? AND pool_address=?"""
    params: list[object] = [run_key, pool]
    if as_of is not None:
        query += " AND observed_at<=?"
        params.append(int(as_of))
    query += " ORDER BY id DESC LIMIT 1"

    with connection() as conn:
        row = conn.execute(query, tuple(params)).fetchone()
    return _row_to_mapping(row) if row is not None else None


def load_known_pumpswap_pool_mapping(
    *,
    pool_address: str,
    as_of: int,
) -> PumpSwapPoolMapping | None:
    """Load a causally known historical pool identity.

    Legacy/history rows with more than one identity are not trusted for reuse; returning ``None``
    forces a fresh RPC resolution instead of crashing or silently choosing an ambiguous identity.
    """

    pool = _required(pool_address, "pool_address")
    decision_time = int(as_of)
    if decision_time < 0:
        raise ValueError("as_of must be non-negative")
    ensure_pumpswap_pool_schema()

    with connection() as conn:
        rows = conn.execute(
            """SELECT acquisition_run_key, pool_address, base_mint, quote_mint,
                observed_at, source_provider
            FROM pumpswap_pool_mappings
            WHERE pool_address=? AND observed_at<=?
            ORDER BY observed_at ASC, id ASC""",
            (pool, decision_time),
        ).fetchall()
    if not rows:
        return None

    identities = {(str(row["base_mint"]), str(row["quote_mint"])) for row in rows}
    if len(identities) != 1:
        return None
    return _row_to_mapping(rows[0])


def count_pumpswap_pool_mapping_conflicts(*, acquisition_run_key: str) -> int:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    ensure_pumpswap_pool_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM pumpswap_pool_mapping_conflicts
            WHERE acquisition_run_key=?""",
            (run_key,),
        ).fetchone()
    return int(row["n"])
