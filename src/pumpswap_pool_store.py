from dataclasses import dataclass

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
"""


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


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
    with connection() as conn:
        conn.executescript(_SCHEMA)


def record_pumpswap_pool_mapping(
    *,
    acquisition_run_key: str,
    pool_address: str,
    base_mint: str,
    quote_mint: str,
    observed_at: int,
    source_provider: str,
) -> bool:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    pool = _required(pool_address, "pool_address")
    base = _required(base_mint, "base_mint")
    quote = _required(quote_mint, "quote_mint")
    provider = _required(source_provider, "source_provider")
    learned_at = int(observed_at)
    if learned_at < 0:
        raise ValueError("observed_at must be non-negative")
    ensure_pumpswap_pool_schema()

    with connection() as conn:
        existing = conn.execute(
            """SELECT base_mint, quote_mint, observed_at, source_provider
            FROM pumpswap_pool_mappings
            WHERE acquisition_run_key=? AND pool_address=?""",
            (run_key, pool),
        ).fetchone()
        if existing is not None:
            actual_identity = (
                str(existing["base_mint"]),
                str(existing["quote_mint"]),
            )
            if actual_identity != (base, quote):
                raise ValueError("PumpSwap pool mapping already exists with different data")
            first_seen = int(existing["observed_at"])
            if learned_at < first_seen:
                raise ValueError("PumpSwap pool replay cannot backdate observed_at")
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
    """Load an identity learned in any earlier run, but only if it was known by ``as_of``.

    Pool base/quote mint identity is immutable chain state for this purpose, so reusing a mapping
    learned in a previous acquisition run avoids needless getAccountInfo calls. Availability is
    still causal: a mapping first learned after the current T0 is invisible. Conflicting historical
    identities are surfaced instead of silently choosing one.
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
        raise ValueError("conflicting historical PumpSwap pool identities")
    return _row_to_mapping(rows[0])
