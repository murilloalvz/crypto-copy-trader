from __future__ import annotations

import json
from dataclasses import dataclass

from src.database import connection
from src.market_observation_store import ensure_market_observation_schema
from src.pump_bonding_stream import PumpLogNotification


@dataclass(frozen=True)
class PumpBatchPersistResult:
    signature: str
    newly_persisted_trades: int
    duplicate_or_replayed_trades: int
    conflicting_trades: int
    newly_persisted_lifecycle: int
    duplicate_or_replayed_lifecycle: int
    conflicting_lifecycle: int
    affected_tokens: tuple[str, ...]


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _ensure_conflict_schema(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pump_replay_conflicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            acquisition_run_key TEXT NOT NULL,
            event_key TEXT NOT NULL,
            signature TEXT NOT NULL,
            event_index INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            stored_observed_at INTEGER NOT NULL,
            incoming_observed_at INTEGER NOT NULL,
            stored_identity_json TEXT NOT NULL,
            incoming_identity_json TEXT NOT NULL,
            canonical_action TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_pump_replay_conflicts_run
        ON pump_replay_conflicts(acquisition_run_key, signature, event_index, id)"""
    )


def _record_conflict(
    conn,
    *,
    run_key: str,
    event_key: str,
    signature: str,
    event_index: int,
    event_type: str,
    stored_observed_at: int,
    incoming_observed_at: int,
    stored_identity: tuple,
    incoming_identity: tuple,
    canonical_action: str,
) -> None:
    _ensure_conflict_schema(conn)
    conn.execute(
        """INSERT INTO pump_replay_conflicts(
            acquisition_run_key, event_key, signature, event_index, event_type,
            stored_observed_at, incoming_observed_at,
            stored_identity_json, incoming_identity_json, canonical_action
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_key,
            event_key,
            signature,
            int(event_index),
            event_type,
            int(stored_observed_at),
            int(incoming_observed_at),
            json.dumps(stored_identity, separators=(",", ":")),
            json.dumps(incoming_identity, separators=(",", ":")),
            canonical_action,
        ),
    )


def _persist_lifecycle_row(
    conn,
    *,
    run_key: str,
    notification: PumpLogNotification,
    index: int,
) -> str:
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
        stored_observed_at = int(existing["observed_at"])
        incoming_observed_at = int(notification.observed_at)
        if stored_identity == identity:
            if incoming_observed_at < stored_observed_at:
                conn.execute(
                    """UPDATE market_lifecycle_observations
                    SET observed_at=?
                    WHERE acquisition_run_key=? AND event_key=?""",
                    (incoming_observed_at, run_key, event_key),
                )
            return "replayed"

        canonical_action = "replace_with_earlier_observation" if incoming_observed_at < stored_observed_at else "retain_earlier_observation"
        _record_conflict(
            conn,
            run_key=run_key,
            event_key=event_key,
            signature=notification.signature,
            event_index=index,
            event_type="lifecycle",
            stored_observed_at=stored_observed_at,
            incoming_observed_at=incoming_observed_at,
            stored_identity=stored_identity,
            incoming_identity=identity,
            canonical_action=canonical_action,
        )
        if incoming_observed_at < stored_observed_at:
            conn.execute(
                """UPDATE market_lifecycle_observations
                SET source_provider=?, token_mint=?, market_started_at=?, observed_at=?, venue=?
                WHERE acquisition_run_key=? AND event_key=?""",
                (
                    identity[0], identity[1], identity[2], incoming_observed_at, identity[3],
                    run_key, event_key,
                ),
            )
        return "conflict"

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
    return "inserted"


def _persist_trade_row(
    conn,
    *,
    run_key: str,
    notification: PumpLogNotification,
    index: int,
) -> str:
    event = notification.events[index]
    if event.sol_amount <= 0:
        return "ignored"
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
        stored_observed_at = int(existing["observed_at"])
        incoming_observed_at = int(notification.observed_at)
        if stored_identity == identity:
            # Concurrent workers can persist a later replay before the earlier websocket delivery.
            # The collector timestamp, not SQLite completion order, defines causal availability.
            if incoming_observed_at < stored_observed_at:
                conn.execute(
                    """UPDATE market_trade_observations
                    SET observed_at=?
                    WHERE acquisition_run_key=? AND event_key=?""",
                    (incoming_observed_at, run_key, event_key),
                )
            return "replayed"

        canonical_action = "replace_with_earlier_observation" if incoming_observed_at < stored_observed_at else "retain_earlier_observation"
        _record_conflict(
            conn,
            run_key=run_key,
            event_key=event_key,
            signature=notification.signature,
            event_index=index,
            event_type="trade",
            stored_observed_at=stored_observed_at,
            incoming_observed_at=incoming_observed_at,
            stored_identity=stored_identity,
            incoming_identity=identity,
            canonical_action=canonical_action,
        )
        if incoming_observed_at < stored_observed_at:
            conn.execute(
                """UPDATE market_trade_observations
                SET source_provider=?, token_mint=?, side=?, chain_time=?, observed_at=?,
                    wallet_address=?, notional_usd=?, price_usd=?, venue=?, transaction_key=?
                WHERE acquisition_run_key=? AND event_key=?""",
                (
                    identity[0], identity[1], identity[2], identity[3], incoming_observed_at,
                    identity[4], identity[5], identity[6], identity[7], identity[8],
                    run_key, event_key,
                ),
            )
        return "conflict"

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
    return "inserted"


def persist_pump_notification_batch(
    notification: PumpLogNotification,
    *,
    acquisition_run_key: str,
) -> PumpBatchPersistResult:
    """Persist one Pump notification using a single SQLite transaction.

    Exact replays are idempotent. With concurrent workers, the earliest collector ``observed_at``
    wins even if a later replay reaches SQLite first. If the same signature/index is replayed with
    a different causal identity, both identities are audited in ``pump_replay_conflicts`` and the
    earliest observed notification remains canonical. Conflicting replays never silently mutate a
    causally earlier observation and no longer crash the acquisition run.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    ensure_market_observation_schema()

    inserted_lifecycle = 0
    replayed_lifecycle = 0
    conflicting_lifecycle = 0
    inserted_trades = 0
    replayed_trades = 0
    conflicting_trades = 0
    affected_tokens: set[str] = set()

    with connection() as conn:
        for index in range(len(notification.lifecycle_events)):
            outcome = _persist_lifecycle_row(
                conn,
                run_key=run_key,
                notification=notification,
                index=index,
            )
            if outcome == "inserted":
                inserted_lifecycle += 1
            elif outcome == "replayed":
                replayed_lifecycle += 1
            elif outcome == "conflict":
                conflicting_lifecycle += 1

        for index, event in enumerate(notification.events):
            if event.sol_amount <= 0:
                continue
            affected_tokens.add(event.mint)
            outcome = _persist_trade_row(
                conn,
                run_key=run_key,
                notification=notification,
                index=index,
            )
            if outcome == "inserted":
                inserted_trades += 1
            elif outcome == "replayed":
                replayed_trades += 1
            elif outcome == "conflict":
                conflicting_trades += 1

    return PumpBatchPersistResult(
        signature=notification.signature,
        newly_persisted_trades=inserted_trades,
        duplicate_or_replayed_trades=replayed_trades,
        conflicting_trades=conflicting_trades,
        newly_persisted_lifecycle=inserted_lifecycle,
        duplicate_or_replayed_lifecycle=replayed_lifecycle,
        conflicting_lifecycle=conflicting_lifecycle,
        affected_tokens=tuple(sorted(affected_tokens)),
    )
