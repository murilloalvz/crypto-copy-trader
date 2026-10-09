from src.database import connection
from src.social_intelligence import SocialEvent


_SCHEMA = """
CREATE TABLE IF NOT EXISTS social_event_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    event_id TEXT NOT NULL,
    author_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    observed_at INTEGER NOT NULL,
    token_mint TEXT,
    symbol TEXT,
    event_type TEXT NOT NULL,
    is_original INTEGER NOT NULL,
    like_count INTEGER NOT NULL DEFAULT 0,
    repost_count INTEGER NOT NULL DEFAULT 0,
    reply_count INTEGER NOT NULL DEFAULT 0,
    quote_count INTEGER NOT NULL DEFAULT 0,
    inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, event_id, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_social_event_token_observed
ON social_event_snapshots(token_mint, observed_at);

CREATE INDEX IF NOT EXISTS idx_social_event_symbol_observed
ON social_event_snapshots(symbol, observed_at);
"""


def ensure_social_event_store_schema() -> None:
    with connection() as conn:
        conn.executescript(_SCHEMA)


def _validate(event: SocialEvent) -> None:
    if not event.source.strip():
        raise ValueError("social event source cannot be empty")
    if not event.event_id.strip():
        raise ValueError("social event id cannot be empty")
    if not event.author_id.strip():
        raise ValueError("social event author_id cannot be empty")
    if event.created_at < 0 or event.observed_at < 0:
        raise ValueError("social event timestamps must be non-negative")
    if event.observed_at < event.created_at:
        raise ValueError("social event observed_at cannot be earlier than created_at")
    if any(
        value < 0
        for value in (
            event.like_count,
            event.repost_count,
            event.reply_count,
            event.quote_count,
        )
    ):
        raise ValueError("social engagement counters cannot be negative")


def record_social_event_snapshot(event: SocialEvent) -> bool:
    """Persist one observed snapshot; repeated observations at new times are retained."""
    _validate(event)
    ensure_social_event_store_schema()
    with connection() as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO social_event_snapshots(
                source, event_id, author_id, created_at, observed_at,
                token_mint, symbol, event_type, is_original,
                like_count, repost_count, reply_count, quote_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.source.strip(),
                event.event_id.strip(),
                event.author_id.strip(),
                event.created_at,
                event.observed_at,
                event.token_mint,
                event.symbol,
                event.event_type,
                1 if event.is_original else 0,
                event.like_count,
                event.repost_count,
                event.reply_count,
                event.quote_count,
            ),
        )
        return cursor.rowcount == 1


def load_social_events(
    *,
    token_mint: str | None = None,
    symbol: str | None = None,
    as_of: int | None = None,
) -> list[SocialEvent]:
    if token_mint is None and symbol is None:
        raise ValueError("token_mint or symbol is required")
    if as_of is not None and as_of < 0:
        raise ValueError("as_of must be non-negative")

    ensure_social_event_store_schema()
    clauses = []
    params: list[object] = []
    if token_mint is not None:
        clauses.append("token_mint=?")
        params.append(token_mint)
    else:
        clauses.append("UPPER(symbol)=UPPER(?)")
        params.append(symbol)
    if as_of is not None:
        clauses.append("observed_at<=?")
        params.append(as_of)

    query = """SELECT source, event_id, author_id, created_at, observed_at,
        token_mint, symbol, event_type, is_original,
        like_count, repost_count, reply_count, quote_count
        FROM social_event_snapshots WHERE """ + " AND ".join(clauses)
    query += " ORDER BY observed_at, source, event_id"

    with connection() as conn:
        result = conn.execute(query, tuple(params)).fetchall()
    return [
        SocialEvent(
            source=str(row["source"]),
            event_id=str(row["event_id"]),
            author_id=str(row["author_id"]),
            created_at=int(row["created_at"]),
            observed_at=int(row["observed_at"]),
            token_mint=row["token_mint"],
            symbol=row["symbol"],
            event_type=str(row["event_type"]),
            is_original=bool(row["is_original"]),
            like_count=int(row["like_count"]),
            repost_count=int(row["repost_count"]),
            reply_count=int(row["reply_count"]),
            quote_count=int(row["quote_count"]),
        )
        for row in result
    ]
