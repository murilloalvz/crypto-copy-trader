from src.causal_quotes import CausalQuoteObservation, validate_causal_quote
from src.database import connection


_SCHEMA = """
CREATE TABLE IF NOT EXISTS causal_quote_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_key TEXT NOT NULL UNIQUE,
    token_mint TEXT NOT NULL,
    market_time INTEGER NOT NULL,
    observed_at INTEGER NOT NULL,
    price_usd REAL NOT NULL,
    liquidity_usd REAL,
    executable INTEGER NOT NULL,
    resolution_seconds INTEGER NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_causal_quotes_token_observed
ON causal_quote_observations(token_mint, observed_at);
"""


def ensure_causal_quote_schema() -> None:
    with connection() as conn:
        conn.executescript(_SCHEMA)


def record_causal_quote(
    quote: CausalQuoteObservation,
    *,
    quote_key: str,
) -> bool:
    validate_causal_quote(quote)
    if not quote_key.strip():
        raise ValueError("quote_key cannot be empty")

    ensure_causal_quote_schema()
    with connection() as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO causal_quote_observations(
                quote_key, token_mint, market_time, observed_at, price_usd,
                liquidity_usd, executable, resolution_seconds, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                quote_key.strip(),
                quote.token_mint.strip(),
                quote.market_time,
                quote.observed_at,
                quote.price_usd,
                quote.liquidity_usd,
                int(quote.executable),
                quote.resolution_seconds,
                quote.source.strip(),
            ),
        )
        return cursor.rowcount == 1


def load_causal_quotes(
    *,
    token_mint: str | None = None,
    as_of: int | None = None,
) -> list[CausalQuoteObservation]:
    if token_mint is not None and not token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    if as_of is not None and as_of < 0:
        raise ValueError("as_of must be non-negative")

    ensure_causal_quote_schema()
    clauses: list[str] = []
    params: list[object] = []
    if token_mint is not None:
        clauses.append("token_mint=?")
        params.append(token_mint.strip())
    if as_of is not None:
        clauses.append("observed_at<=?")
        params.append(as_of)

    query = """SELECT token_mint, market_time, observed_at, price_usd,
        liquidity_usd, executable, resolution_seconds, source
        FROM causal_quote_observations"""
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY observed_at, id"

    with connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [
        CausalQuoteObservation(
            token_mint=str(row["token_mint"]),
            market_time=int(row["market_time"]),
            observed_at=int(row["observed_at"]),
            price_usd=float(row["price_usd"]),
            liquidity_usd=(
                float(row["liquidity_usd"])
                if row["liquidity_usd"] is not None
                else None
            ),
            executable=bool(row["executable"]),
            resolution_seconds=int(row["resolution_seconds"]),
            source=str(row["source"]),
        )
        for row in rows
    ]
