from src.causal_quotes import CausalQuoteObservation, validate_causal_quote
from src.database import connection


_SCHEMA = """
CREATE TABLE IF NOT EXISTS causal_quote_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_key TEXT NOT NULL UNIQUE,
    token_mint TEXT NOT NULL,
    side TEXT NOT NULL,
    market_time INTEGER NOT NULL,
    observed_at INTEGER NOT NULL,
    price_usd REAL NOT NULL,
    liquidity_usd REAL,
    executable INTEGER NOT NULL,
    resolution_seconds INTEGER NOT NULL,
    source TEXT NOT NULL,
    input_mint TEXT,
    output_mint TEXT,
    input_amount_raw TEXT,
    output_amount_raw TEXT,
    route_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_causal_quotes_token_side_observed
ON causal_quote_observations(token_mint, side, observed_at);
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
                quote_key, token_mint, side, market_time, observed_at, price_usd,
                liquidity_usd, executable, resolution_seconds, source,
                input_mint, output_mint, input_amount_raw, output_amount_raw, route_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                quote_key.strip(),
                quote.token_mint.strip(),
                quote.side,
                quote.market_time,
                quote.observed_at,
                quote.price_usd,
                quote.liquidity_usd,
                int(quote.executable),
                quote.resolution_seconds,
                quote.source.strip(),
                quote.input_mint,
                quote.output_mint,
                quote.input_amount_raw,
                quote.output_amount_raw,
                quote.route_id,
            ),
        )
        return cursor.rowcount == 1


def load_causal_quotes(
    *,
    token_mint: str | None = None,
    side: str | None = None,
    as_of: int | None = None,
    quote_keys: tuple[str, ...] | list[str] | None = None,
) -> list[CausalQuoteObservation]:
    if token_mint is not None and not token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    if side is not None and side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if as_of is not None and as_of < 0:
        raise ValueError("as_of must be non-negative")

    normalized_quote_keys: tuple[str, ...] | None = None
    if quote_keys is not None:
        normalized_quote_keys = tuple(
            dict.fromkeys(str(item).strip() for item in quote_keys if str(item).strip())
        )
        # An explicit empty set means "load nothing". This matters for experiment-scoped
        # replay: falling back to every persisted quote would contaminate the cohort.
        if not normalized_quote_keys:
            return []

    ensure_causal_quote_schema()
    clauses: list[str] = []
    params: list[object] = []
    if token_mint is not None:
        clauses.append("token_mint=?")
        params.append(token_mint.strip())
    if side is not None:
        clauses.append("side=?")
        params.append(side)
    if as_of is not None:
        clauses.append("observed_at<=?")
        params.append(as_of)
    if normalized_quote_keys is not None:
        placeholders = ",".join("?" for _ in normalized_quote_keys)
        clauses.append(f"quote_key IN ({placeholders})")
        params.extend(normalized_quote_keys)

    query = """SELECT token_mint, side, market_time, observed_at, price_usd,
        liquidity_usd, executable, resolution_seconds, source,
        input_mint, output_mint, input_amount_raw, output_amount_raw, route_id
        FROM causal_quote_observations"""
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY observed_at, id"

    with connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [
        CausalQuoteObservation(
            token_mint=str(row["token_mint"]),
            side=str(row["side"]),
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
            input_mint=row["input_mint"],
            output_mint=row["output_mint"],
            input_amount_raw=row["input_amount_raw"],
            output_amount_raw=row["output_amount_raw"],
            route_id=row["route_id"],
        )
        for row in rows
    ]
