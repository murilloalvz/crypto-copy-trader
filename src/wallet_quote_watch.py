from dataclasses import dataclass

from src.database import connection
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema


@dataclass(frozen=True)
class ForwardBuyEvent:
    id: int
    observation_key: str
    wallet_address: str
    token_mint: str
    chain_time: int
    observed_at: int


@dataclass(frozen=True)
class ScheduledQuoteProbe:
    event_id: int
    observation_key: str
    wallet_address: str
    token_mint: str
    wallet_chain_time: int
    wallet_observed_at: int
    delay_seconds: int
    target_at: int

    @property
    def attempt_key(self) -> str:
        return f"wallet-forward:{self.event_id}:buy:+{self.delay_seconds}s:jupiter-v2"

    @property
    def quote_key(self) -> str:
        return self.attempt_key


_ATTEMPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS causal_quote_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_key TEXT NOT NULL UNIQUE,
    source_event_key TEXT NOT NULL,
    wallet_address TEXT,
    token_mint TEXT NOT NULL,
    side TEXT NOT NULL,
    target_at INTEGER NOT NULL,
    requested_at INTEGER NOT NULL,
    completed_at INTEGER NOT NULL,
    status TEXT NOT NULL,
    quote_key TEXT,
    error_class TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_quote_attempts_token_target
ON causal_quote_attempts(token_mint, side, target_at);
"""


def ensure_quote_attempt_schema() -> None:
    with connection() as conn:
        conn.executescript(_ATTEMPT_SCHEMA)


def latest_forward_observation_id() -> int:
    ensure_wallet_forward_observation_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS max_id FROM wallet_forward_observations"
        ).fetchone()
    return int(row["max_id"])


def load_forward_buys_after(
    after_id: int,
    *,
    wallet_addresses: tuple[str, ...] | list[str] | None = None,
) -> list[ForwardBuyEvent]:
    if after_id < 0:
        raise ValueError("after_id must be non-negative")
    addresses = tuple(
        dict.fromkeys(item.strip() for item in (wallet_addresses or []) if item.strip())
    )
    ensure_wallet_forward_observation_schema()
    query = """SELECT id, observation_key, wallet_address, token_mint, chain_time, observed_at
        FROM wallet_forward_observations
        WHERE id > ? AND side='buy'"""
    params: list[object] = [after_id]
    if addresses:
        placeholders = ",".join("?" for _ in addresses)
        query += f" AND wallet_address IN ({placeholders})"
        params.extend(addresses)
    query += " ORDER BY id"
    with connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [
        ForwardBuyEvent(
            id=int(row["id"]),
            observation_key=str(row["observation_key"]),
            wallet_address=str(row["wallet_address"]),
            token_mint=str(row["token_mint"]),
            chain_time=int(row["chain_time"]),
            observed_at=int(row["observed_at"]),
        )
        for row in rows
    ]


def schedule_buy_quotes(
    events: list[ForwardBuyEvent] | tuple[ForwardBuyEvent, ...],
    *,
    delays_seconds: tuple[int, ...] | list[int],
) -> list[ScheduledQuoteProbe]:
    delays = tuple(dict.fromkeys(int(item) for item in delays_seconds))
    if not delays:
        raise ValueError("at least one quote delay is required")
    if any(item < 0 for item in delays):
        raise ValueError("quote delays must be non-negative")

    probes = [
        ScheduledQuoteProbe(
            event_id=event.id,
            observation_key=event.observation_key,
            wallet_address=event.wallet_address,
            token_mint=event.token_mint,
            wallet_chain_time=event.chain_time,
            wallet_observed_at=event.observed_at,
            delay_seconds=delay,
            target_at=event.observed_at + delay,
        )
        for event in events
        for delay in delays
    ]
    return sorted(probes, key=lambda item: (item.target_at, item.event_id, item.delay_seconds))


def record_quote_attempt(
    probe: ScheduledQuoteProbe,
    *,
    requested_at: int,
    completed_at: int,
    status: str,
    quote_key: str | None = None,
    error: BaseException | None = None,
) -> bool:
    if requested_at < 0 or completed_at < requested_at:
        raise ValueError("invalid quote attempt timestamps")
    if status not in {"success", "error"}:
        raise ValueError("quote attempt status must be success or error")
    if status == "success" and not quote_key:
        raise ValueError("successful quote attempt requires quote_key")
    if status == "error" and error is None:
        raise ValueError("failed quote attempt requires error")

    ensure_quote_attempt_schema()
    with connection() as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO causal_quote_attempts(
                attempt_key, source_event_key, wallet_address, token_mint, side,
                target_at, requested_at, completed_at, status, quote_key,
                error_class, error_message
            ) VALUES (?, ?, ?, ?, 'buy', ?, ?, ?, ?, ?, ?, ?)""",
            (
                probe.attempt_key,
                probe.observation_key,
                probe.wallet_address,
                probe.token_mint,
                probe.target_at,
                requested_at,
                completed_at,
                status,
                quote_key,
                type(error).__name__ if error is not None else None,
                str(error)[:500] if error is not None else None,
            ),
        )
        return cursor.rowcount == 1


def quote_attempt_exists(attempt_key: str) -> bool:
    if not attempt_key.strip():
        raise ValueError("attempt_key cannot be empty")
    ensure_quote_attempt_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM causal_quote_attempts WHERE attempt_key=? LIMIT 1",
            (attempt_key.strip(),),
        ).fetchone()
    return row is not None
