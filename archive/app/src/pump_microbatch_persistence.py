from __future__ import annotations

from collections.abc import Sequence

from src.database import connection
from src.market_observation_store import ensure_market_observation_schema
from src.pump_batch_persistence import (
    PumpBatchPersistResult,
    _persist_lifecycle_row,
    _persist_trade_row,
    _required,
)
from src.pump_bonding_stream import PumpLogNotification


def persist_pump_notifications_microbatch(
    notifications: Sequence[PumpLogNotification],
    *,
    acquisition_run_key: str,
) -> tuple[PumpBatchPersistResult, ...]:
    """Persist multiple Pump websocket notifications in one SQLite transaction.

    Input order is preserved exactly. The function deliberately reuses the already-tested
    per-event replay/canonicalization helpers from ``pump_batch_persistence``; the optimization is
    only transaction amortization, not a semantic change. A genuinely unexpected exception rolls
    back the whole microbatch so acquisition still fails loudly instead of leaving a partially
    committed batch.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    batch = tuple(notifications)
    if not batch:
        return ()

    ensure_market_observation_schema()
    results: list[PumpBatchPersistResult] = []

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

            results.append(
                PumpBatchPersistResult(
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
