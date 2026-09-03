from __future__ import annotations

from dataclasses import dataclass

from src.database import connection
from src.market_observation_store import ensure_market_observation_schema
from src.pump_bonding_stream import PumpLogNotification


@dataclass(frozen=True)
class PumpBatchPersistResult:
    signature: str
    newly_persisted_trades: int
    duplicate_or_replayed_trades: int
    newly_persisted_lifecycle: int
    duplicate_or_replayed_lifecycle: int
    affected_tokens: tuple[str, ...]


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _persist_lifecycle_row(conn, *, run_key: str, notification: PumpLogNotification, index: int) -> bool:
    event = notification.lifecycle_events[index]
    event_key = f"pump-create:{notification.signature}:{index}"
    existing = conn.execute(
        """SELECT source_provider, token_mint, market_started_at, observed_at, venue
        FROM market_lifecycle_observations
        WHERE acquisition_run_key=? AND event_key=?""",
        (run_key, event_key),
    ).fetchone()
    identity = ("solana_logs_subscribe", event.mint, int(event.timestamp), "pump_bonding_curve")
    if existing is not None:
        stored_identity = (
            str(existing["source_provider"]),
            str(existing["token_mint"]),
            int(existing["market_started_at"]),
            str(existing["venue"]) if existing["venue"] is not None else None,
        )
        if stored_identity != identity:
            raise ValueError("market lifecycle event already exists with different data")
        if int(notification.observed_at) < int(existing["observed_at"]):
            raise ValueError("market lifecycle replay observed_at precedes first observation")
        return False

    conn.execute(
        """INSERT INTO market_lifecycle_observations(
            acquisition_run_key, event_key, source_provider, token_mint,
            market_started_at, observed_at, venue
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            run_key,
            event_key,
            "solana_logs_subscribe",
            event.mint,
            int(event.timestamp),
            int(notification.observed_at),
            "pump_bonding_curve",
        ),
    )
    return True


def _persist_trade_row(conn, *, run_key: str, notification: PumpLogNotification, index: int) -> bool:
    event = notification.events[index]
    if event.sol_amount <= 0:
        return False
    event_key = f"pump:{notification.signature}:{index}"
    side = "buy" if event.is_buy else "sell"
    identity = (
        "solana_logs_subscribe",
        event.mint,
        side,
        int(event.timestamp),
        event.user,
        None,
        None,
        "pump_bonding_curve",
        notification.signature,
    )
    existing = conn.execute(
        """SELECT source_provider, token_mint, side, chain_time, observed_at,
            wallet_address, notional_usd, price_usd, venue, transaction_key
        FROM market_trade_observations
        WHERE acquisition_run_key=? AND event_key=?""",
        (run_key, event_key),
    ).fetchone()
    if existing is not None:
        stored_identity = (
            str(existing["source_provider"]),
            str(existing["token_mint"]),
            str(existing["side"]),
            int(existing["chain_time"]),
            str(existing["wallet_address"]) if existing["wallet_address"] is not None else None,
            float(existing["notional_usd"]) if existing["notional_usd"] is not None else None,
            float(existing["price_usd"]) if existing["price_usd"] is not None else None,
            str(existing["venue"]) if existing["venue"] is not None else None,
            str(existing["transaction_key"]) if existing["transaction_key"] is not None else None,
        )
        if stored_identity != identity:
            raise ValueError("market trade event already exists with different data")
        if int(notification.observed_at) < int(existing["observed_at"]):
            raise ValueError("market trade replay observed_at precedes first observation")
        return False

    conn.execute(
        """INSERT INTO market_trade_observations(
            acquisition_run_key, event_key, source_provider, token_mint, side,
            chain_time, observed_at, wallet_address, notional_usd, price_usd, venue,
            transaction_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_key,
            event_key,
            "solana_logs_subscribe",
            event.mint,
            side,
            int(event.timestamp),
            int(notification.observed_at),
            event.user,
            None,
            None,
            "pump_bonding_curve",
            notification.signature,
        ),
    )
    return True


def persist_pump_notification_batch(
    notification: PumpLogNotification,
    *,
    acquisition_run_key: str,
) -> PumpBatchPersistResult:
    """Persist one Pump notification using a single SQLite transaction.

    Semantics intentionally match ``persist_pump_notification``: exact later replays are
    idempotent, the first observed_at remains authoritative, backdating is rejected, and only
    SOL-paired TradeEvents (positive sol_amount) enter the normalized market store.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    ensure_market_observation_schema()

    inserted_lifecycle = 0
    replayed_lifecycle = 0
    inserted_trades = 0
    replayed_trades = 0
    affected_tokens: set[str] = set()

    with connection() as conn:
        for index in range(len(notification.lifecycle_events)):
            if _persist_lifecycle_row(conn, run_key=run_key, notification=notification, index=index):
                inserted_lifecycle += 1
            else:
                replayed_lifecycle += 1

        for index, event in enumerate(notification.events):
            if event.sol_amount <= 0:
                continue
            affected_tokens.add(event.mint)
            if _persist_trade_row(conn, run_key=run_key, notification=notification, index=index):
                inserted_trades += 1
            else:
                replayed_trades += 1

    return PumpBatchPersistResult(
        signature=notification.signature,
        newly_persisted_trades=inserted_trades,
        duplicate_or_replayed_trades=replayed_trades,
        newly_persisted_lifecycle=inserted_lifecycle,
        duplicate_or_replayed_lifecycle=replayed_lifecycle,
        affected_tokens=tuple(sorted(affected_tokens)),
    )
