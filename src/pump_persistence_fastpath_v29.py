from __future__ import annotations

from dataclasses import dataclass
import threading

from src.database import connection
from src.market_observation_store import ensure_market_observation_schema
import src.pump_batch_persistence as pump_batch


@dataclass(frozen=True)
class PumpPersistenceFastPathSnapshot:
    trade_insert_attempts: int
    trade_collision_reads: int
    lifecycle_insert_attempts: int
    lifecycle_collision_reads: int


_STATS_LOCK = threading.Lock()
_STATS = {
    "trade_insert_attempts": 0,
    "trade_collision_reads": 0,
    "lifecycle_insert_attempts": 0,
    "lifecycle_collision_reads": 0,
}


def reset_pump_persistence_fastpath_metrics() -> None:
    with _STATS_LOCK:
        for key in _STATS:
            _STATS[key] = 0


def pump_persistence_fastpath_snapshot() -> PumpPersistenceFastPathSnapshot:
    with _STATS_LOCK:
        return PumpPersistenceFastPathSnapshot(**dict(_STATS))


def _add_stat(key: str, amount: int = 1) -> None:
    with _STATS_LOCK:
        _STATS[key] += int(amount)


def _persist_lifecycle_optimistic(conn, *, run_key: str, notification, index: int) -> str:
    event = notification.lifecycle_events[index]
    event_key = f"pump-create:{notification.signature}:{index}"
    identity = ("solana_logs_subscribe", event.mint, int(event.timestamp), "pump_bonding_curve")
    incoming_observed_at = int(notification.observed_at)

    _add_stat("lifecycle_insert_attempts")
    cursor = conn.execute(
        """INSERT OR IGNORE INTO market_lifecycle_observations(
            acquisition_run_key, event_key, source_provider, token_mint,
            market_started_at, observed_at, venue
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            run_key,
            event_key,
            identity[0],
            identity[1],
            identity[2],
            incoming_observed_at,
            identity[3],
        ),
    )
    if cursor.rowcount == 1:
        return "inserted"

    _add_stat("lifecycle_collision_reads")
    existing = conn.execute(
        """SELECT source_provider, token_mint, market_started_at, observed_at, venue
        FROM market_lifecycle_observations
        WHERE acquisition_run_key=? AND event_key=?""",
        (run_key, event_key),
    ).fetchone()
    if existing is None:
        raise RuntimeError("Pump lifecycle INSERT OR IGNORE lost canonical row")

    stored_identity = (
        str(existing["source_provider"]),
        str(existing["token_mint"]),
        int(existing["market_started_at"]),
        str(existing["venue"]) if existing["venue"] is not None else None,
    )
    stored_observed_at = int(existing["observed_at"])
    if stored_identity == identity:
        if incoming_observed_at < stored_observed_at:
            conn.execute(
                """UPDATE market_lifecycle_observations SET observed_at=?
                WHERE acquisition_run_key=? AND event_key=?""",
                (incoming_observed_at, run_key, event_key),
            )
        return "replayed"

    canonical_action = (
        "replace_with_earlier_observation"
        if incoming_observed_at < stored_observed_at
        else "retain_earlier_observation"
    )
    pump_batch._record_conflict(
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
                identity[0],
                identity[1],
                identity[2],
                incoming_observed_at,
                identity[3],
                run_key,
                event_key,
            ),
        )
    return "conflict"


def _persist_trade_optimistic(conn, *, run_key: str, notification, index: int) -> str:
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
    incoming_observed_at = int(notification.observed_at)

    _add_stat("trade_insert_attempts")
    cursor = conn.execute(
        """INSERT OR IGNORE INTO market_trade_observations(
            acquisition_run_key, event_key, source_provider, token_mint, side,
            chain_time, observed_at, wallet_address, notional_usd, price_usd, venue,
            transaction_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_key,
            event_key,
            identity[0],
            identity[1],
            identity[2],
            identity[3],
            incoming_observed_at,
            identity[4],
            identity[5],
            identity[6],
            identity[7],
            identity[8],
        ),
    )
    if cursor.rowcount == 1:
        return "inserted"

    _add_stat("trade_collision_reads")
    existing = conn.execute(
        """SELECT source_provider, token_mint, side, chain_time, observed_at,
            wallet_address, notional_usd, price_usd, venue, transaction_key
        FROM market_trade_observations
        WHERE acquisition_run_key=? AND event_key=?""",
        (run_key, event_key),
    ).fetchone()
    if existing is None:
        raise RuntimeError("Pump trade INSERT OR IGNORE lost canonical row")

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
    if stored_identity == identity:
        if incoming_observed_at < stored_observed_at:
            conn.execute(
                """UPDATE market_trade_observations SET observed_at=?
                WHERE acquisition_run_key=? AND event_key=?""",
                (incoming_observed_at, run_key, event_key),
            )
        return "replayed"

    canonical_action = (
        "replace_with_earlier_observation"
        if incoming_observed_at < stored_observed_at
        else "retain_earlier_observation"
    )
    pump_batch._record_conflict(
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
                identity[0],
                identity[1],
                identity[2],
                identity[3],
                incoming_observed_at,
                identity[4],
                identity[5],
                identity[6],
                identity[7],
                identity[8],
                run_key,
                event_key,
            ),
        )
    return "conflict"


def persist_pump_notifications_microbatch_fast_v29(notifications, *, acquisition_run_key: str):
    run_key = pump_batch._required(acquisition_run_key, "acquisition_run_key")
    batch = tuple(notifications)
    if not batch:
        return ()
    ensure_market_observation_schema()
    results = []

    with connection() as conn:
        for notification in batch:
            inserted_lifecycle = 0
            replayed_lifecycle = 0
            conflicting_lifecycle = 0
            inserted_trades = 0
            replayed_trades = 0
            conflicting_trades = 0
            affected_tokens: set[str] = set()

            for index in range(len(notification.lifecycle_events)):
                outcome = _persist_lifecycle_optimistic(
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
                outcome = _persist_trade_optimistic(
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

            results.append(
                pump_batch.PumpBatchPersistResult(
                    signature=notification.signature,
                    newly_persisted_trades=inserted_trades,
                    duplicate_or_replayed_trades=replayed_trades,
                    conflicting_trades=conflicting_trades,
                    newly_persisted_lifecycle=inserted_lifecycle,
                    duplicate_or_replayed_lifecycle=replayed_lifecycle,
                    conflicting_lifecycle=conflicting_lifecycle,
                    affected_tokens=tuple(sorted(affected_tokens)),
                )
            )

    return tuple(results)
