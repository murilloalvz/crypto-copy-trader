from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import threading
import time

from src.database import connection
from src.market_observation_store import ensure_market_observation_schema
from src.pumpswap_normalized_persistence import PumpSwapNormalizedPersistResult
import src.pumpswap_normalized_persistence_v3 as v3


@dataclass(frozen=True)
class PumpSwapPersistenceFastPathSnapshot:
    prepared_items: int
    trade_insert_attempts: int
    trade_collision_reads: int
    lifecycle_insert_attempts: int
    lifecycle_collision_reads: int
    affected_token_batch_readbacks: int


_STATS_LOCK = threading.Lock()
_STATS = {
    "prepared_items": 0,
    "trade_insert_attempts": 0,
    "trade_collision_reads": 0,
    "lifecycle_insert_attempts": 0,
    "lifecycle_collision_reads": 0,
    "affected_token_batch_readbacks": 0,
}


def reset_pumpswap_persistence_fastpath_metrics() -> None:
    with _STATS_LOCK:
        for key in _STATS:
            _STATS[key] = 0


def pumpswap_persistence_fastpath_snapshot() -> PumpSwapPersistenceFastPathSnapshot:
    with _STATS_LOCK:
        return PumpSwapPersistenceFastPathSnapshot(**dict(_STATS))


def _add_stat(key: str, amount: int = 1) -> None:
    with _STATS_LOCK:
        _STATS[key] += int(amount)


def _stored_lifecycle_identity(row) -> tuple:
    return (
        str(row["source_provider"]),
        str(row["token_mint"]),
        int(row["market_started_at"]),
        str(row["venue"]) if row["venue"] is not None else None,
    )


def _record_lifecycle_optimistic(conn, *, run_key: str, item) -> bool:
    raw_key = v3._store_required(item.event_key, "event_key")
    observation = item.observation
    v3._validate_lifecycle(observation)
    identity_values = (
        v3._SOURCE_PROVIDER,
        observation.token_mint,
        observation.market_started_at,
        observation.venue,
    )
    _add_stat("lifecycle_insert_attempts")
    cursor = conn.execute(
        """INSERT OR IGNORE INTO market_lifecycle_observations(
            acquisition_run_key, event_key, source_provider, token_mint,
            market_started_at, observed_at, venue
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            run_key,
            raw_key,
            v3._SOURCE_PROVIDER,
            observation.token_mint,
            observation.market_started_at,
            observation.observed_at,
            observation.venue,
        ),
    )
    if cursor.rowcount == 1:
        return True

    _add_stat("lifecycle_collision_reads")
    existing = conn.execute(
        """SELECT source_provider, token_mint, market_started_at, observed_at, venue
        FROM market_lifecycle_observations
        WHERE acquisition_run_key=? AND event_key=?""",
        (run_key, raw_key),
    ).fetchone()
    if existing is None:
        raise RuntimeError("PumpSwap lifecycle INSERT OR IGNORE lost canonical row")

    stored_identity = _stored_lifecycle_identity(existing)
    stored_observed_at = int(existing["observed_at"])
    incoming_observed_at = int(observation.observed_at)
    if stored_identity == identity_values:
        if incoming_observed_at < stored_observed_at:
            conn.execute(
                """UPDATE market_lifecycle_observations SET observed_at=?
                WHERE acquisition_run_key=? AND event_key=?""",
                (incoming_observed_at, run_key, raw_key),
            )
        return False

    action, incoming_wins = v3._choose_conflict_action(
        stored_observed_at=stored_observed_at,
        incoming_observed_at=incoming_observed_at,
        stored_identity=stored_identity,
        incoming_identity=identity_values,
    )
    v3._record_replay_conflict(
        conn,
        acquisition_run_key=run_key,
        event_key=raw_key,
        event_type="lifecycle",
        source_provider=v3._SOURCE_PROVIDER,
        stored_observed_at=stored_observed_at,
        incoming_observed_at=incoming_observed_at,
        stored_identity=stored_identity,
        incoming_identity=identity_values,
        canonical_action=action,
    )
    if incoming_wins:
        conn.execute(
            """UPDATE market_lifecycle_observations
            SET source_provider=?, token_mint=?, market_started_at=?, observed_at=?, venue=?
            WHERE acquisition_run_key=? AND event_key=?""",
            (
                v3._SOURCE_PROVIDER,
                observation.token_mint,
                observation.market_started_at,
                incoming_observed_at,
                observation.venue,
                run_key,
                raw_key,
            ),
        )
    return False


def _stored_trade_identity(row) -> tuple:
    return (
        str(row["source_provider"]),
        str(row["token_mint"]),
        str(row["side"]),
        int(row["chain_time"]),
        str(row["wallet_address"]) if row["wallet_address"] is not None else None,
        float(row["notional_usd"]) if row["notional_usd"] is not None else None,
        float(row["price_usd"]) if row["price_usd"] is not None else None,
        str(row["venue"]) if row["venue"] is not None else None,
        str(row["transaction_key"]) if row["transaction_key"] is not None else None,
    )


def _record_trade_optimistic(conn, *, run_key: str, item) -> bool:
    raw_key = v3._store_required(item.event_key, "event_key")
    observation = item.observation
    v3._validate_trade(observation)
    identity_values = (
        v3._SOURCE_PROVIDER,
        observation.token_mint,
        observation.side,
        observation.chain_time,
        observation.wallet_address,
        observation.notional_usd,
        observation.price_usd,
        observation.venue,
        observation.transaction_key,
    )
    _add_stat("trade_insert_attempts")
    cursor = conn.execute(
        """INSERT OR IGNORE INTO market_trade_observations(
            acquisition_run_key, event_key, source_provider, token_mint, side,
            chain_time, observed_at, wallet_address, notional_usd, price_usd, venue,
            transaction_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_key,
            raw_key,
            v3._SOURCE_PROVIDER,
            observation.token_mint,
            observation.side,
            observation.chain_time,
            observation.observed_at,
            observation.wallet_address,
            observation.notional_usd,
            observation.price_usd,
            observation.venue,
            observation.transaction_key,
        ),
    )
    if cursor.rowcount == 1:
        return True

    _add_stat("trade_collision_reads")
    existing = conn.execute(
        """SELECT source_provider, token_mint, side, chain_time, observed_at,
            wallet_address, notional_usd, price_usd, venue, transaction_key
        FROM market_trade_observations
        WHERE acquisition_run_key=? AND event_key=?""",
        (run_key, raw_key),
    ).fetchone()
    if existing is None:
        raise RuntimeError("PumpSwap trade INSERT OR IGNORE lost canonical row")

    stored_identity = _stored_trade_identity(existing)
    stored_observed_at = int(existing["observed_at"])
    incoming_observed_at = int(observation.observed_at)
    if stored_identity == identity_values:
        if incoming_observed_at < stored_observed_at:
            conn.execute(
                """UPDATE market_trade_observations SET observed_at=?
                WHERE acquisition_run_key=? AND event_key=?""",
                (incoming_observed_at, run_key, raw_key),
            )
        return False

    action, incoming_wins = v3._choose_conflict_action(
        stored_observed_at=stored_observed_at,
        incoming_observed_at=incoming_observed_at,
        stored_identity=stored_identity,
        incoming_identity=identity_values,
    )
    v3._record_replay_conflict(
        conn,
        acquisition_run_key=run_key,
        event_key=raw_key,
        event_type="trade",
        source_provider=v3._SOURCE_PROVIDER,
        stored_observed_at=stored_observed_at,
        incoming_observed_at=incoming_observed_at,
        stored_identity=stored_identity,
        incoming_identity=identity_values,
        canonical_action=action,
    )
    if incoming_wins:
        conn.execute(
            """UPDATE market_trade_observations
            SET source_provider=?, token_mint=?, side=?, chain_time=?, observed_at=?,
                wallet_address=?, notional_usd=?, price_usd=?, venue=?, transaction_key=?
            WHERE acquisition_run_key=? AND event_key=?""",
            (
                v3._SOURCE_PROVIDER,
                observation.token_mint,
                observation.side,
                observation.chain_time,
                incoming_observed_at,
                observation.wallet_address,
                observation.notional_usd,
                observation.price_usd,
                observation.venue,
                observation.transaction_key,
                run_key,
                raw_key,
            ),
        )
    return False


def _load_batch_affected_tokens(conn, prepared_items) -> dict[tuple[str, str], tuple[str, ...]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for prepared in prepared_items:
        grouped[prepared.acquisition_run_key].append(prepared.transaction_key)

    result: dict[tuple[str, str], tuple[str, ...]] = {}
    for run_key, transaction_keys in grouped.items():
        unique_keys = tuple(dict.fromkeys(transaction_keys))
        if not unique_keys:
            continue
        placeholders = ",".join("?" for _ in unique_keys)
        rows = conn.execute(
            f"""SELECT transaction_key, token_mint
            FROM market_trade_observations
            WHERE acquisition_run_key=? AND venue='pumpswap'
              AND transaction_key IN ({placeholders})
            ORDER BY transaction_key, token_mint, id""",
            (run_key, *unique_keys),
        ).fetchall()
        _add_stat("affected_token_batch_readbacks")
        tokens: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            tokens[str(row["transaction_key"])].add(str(row["token_mint"]))
        for transaction_key in unique_keys:
            result[(run_key, transaction_key)] = tuple(sorted(tokens.get(transaction_key, set())))
    return result


def persist_prepared_batch_fast_v29(prepared_items):
    """Persist a PumpSwap microbatch with insert-first replay checks and one batch readback.

    Semantics match v3/v4: earliest observed_at stays canonical, conflicting replay remains
    auditable, and affected_tokens is read back from the authoritative persisted store. The hot
    path avoids one pre-insert SELECT per new row and replaces one transaction-token SELECT per
    notification with one SELECT per run/microbatch.
    """

    prepared_items = tuple(prepared_items)
    if not prepared_items:
        now = time.perf_counter()
        return (), now, now
    ensure_market_observation_schema()
    _add_stat("prepared_items", len(prepared_items))

    writer_started = time.perf_counter()
    interim: list[tuple[object, int, int]] = []
    with connection() as conn:
        for prepared in prepared_items:
            newly_persisted_lifecycle = 0
            for item in prepared.lifecycle_writes:
                if _record_lifecycle_optimistic(
                    conn,
                    run_key=prepared.acquisition_run_key,
                    item=item,
                ):
                    newly_persisted_lifecycle += 1

            inserted = 0
            duplicates = 0
            for item in prepared.trade_writes:
                if _record_trade_optimistic(
                    conn,
                    run_key=prepared.acquisition_run_key,
                    item=item,
                ):
                    inserted += 1
                else:
                    duplicates += 1
            interim.append((prepared, newly_persisted_lifecycle, inserted, duplicates))

        affected_by_transaction = _load_batch_affected_tokens(conn, prepared_items)
        results = tuple(
            PumpSwapNormalizedPersistResult(
                newly_persisted_trades=inserted,
                duplicate_or_replayed_trades=duplicates,
                unresolved_trades=prepared.unresolved_trades,
                role_filtered_trades=prepared.role_filtered_trades,
                newly_persisted_lifecycle=newly_persisted_lifecycle,
                role_filtered_lifecycle=prepared.role_filtered_lifecycle,
                affected_tokens=affected_by_transaction.get(
                    (prepared.acquisition_run_key, prepared.transaction_key),
                    (),
                ),
            )
            for prepared, newly_persisted_lifecycle, inserted, duplicates in interim
        )

    writer_finished = time.perf_counter()
    return results, writer_started, writer_finished
