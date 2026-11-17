from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Sequence

from src.database import connection
from src.market_opportunity_episode_store import (
    _load_episode_row,
    _record_trigger_conflict,
    _required,
    _row_to_episode,
    _run_with_sqlite_lock_retry,
    ensure_market_opportunity_episode_schema,
)


@dataclass(frozen=True)
class MarketContinuationTriggerWriteV0:
    acquisition_run_key: str
    episode_key: str
    trigger_key: str
    token_mint: str
    trigger_kind: str
    direction: str
    chain_time: int
    observed_at: int
    method_version: str
    venue: str | None


@dataclass(frozen=True)
class MarketContinuationTriggerBatchResultV0:
    attempted: int
    inserted: int
    replayed: int
    conflicts: int


def _validate_item(item: MarketContinuationTriggerWriteV0) -> tuple[str, str, str, str, str, int, int, str, str | None]:
    run_key = _required(item.acquisition_run_key, "acquisition_run_key")
    episode_key = _required(item.episode_key, "episode_key")
    trigger_key = _required(item.trigger_key, "trigger_key")
    token_mint = _required(item.token_mint, "token_mint")
    trigger_kind = _required(item.trigger_kind, "trigger_kind")
    direction = _required(item.direction, "direction")
    method_version = _required(item.method_version, "method_version")
    chain_time = int(item.chain_time)
    observed_at = int(item.observed_at)
    if chain_time < 0 or observed_at < 0:
        raise ValueError("trigger timestamps must be non-negative")
    venue = None if item.venue is None else _required(item.venue, "venue")
    return (
        run_key,
        episode_key,
        trigger_key,
        token_mint,
        trigger_kind,
        chain_time,
        observed_at,
        method_version,
        venue,
    )


def record_market_continuation_triggers_batch_v0(
    items: Sequence[MarketContinuationTriggerWriteV0],
) -> MarketContinuationTriggerBatchResultV0:
    """Persist already-classified continuation triggers in one SQLite transaction.

    The Signal Plane may use this API only after a canonical episode has already been
    persisted synchronously. Every item is revalidated against that episode and must
    fall inside its existing local-clock window. This deliberately cannot create a new
    episode or move T0; those operations remain Signal-Plane synchronous.
    """
    if not items:
        return MarketContinuationTriggerBatchResultV0(
            attempted=0, inserted=0, replayed=0, conflicts=0
        )
    ensure_market_opportunity_episode_schema()

    def persist_once() -> MarketContinuationTriggerBatchResultV0:
        inserted = 0
        conflicts = 0
        with connection() as conn:
            for item in items:
                (
                    run_key,
                    episode_key,
                    trigger_key,
                    token_mint,
                    trigger_kind,
                    chain_time,
                    observed_at,
                    method_version,
                    venue,
                ) = _validate_item(item)
                direction = _required(item.direction, "direction")

                episode_row = _load_episode_row(conn, episode_key)
                if episode_row is None:
                    raise ValueError(f"continuation trigger episode not found: {episode_key}")
                episode = _row_to_episode(episode_row)
                if episode.acquisition_run_key != run_key or episode.token_mint != token_mint:
                    raise ValueError("continuation trigger conflicts with canonical episode identity")
                if trigger_key == episode.first_trigger_key:
                    raise ValueError("first trigger cannot be written through continuation batch")
                if not (
                    episode.first_trigger_observed_at <= observed_at < episode.episode_closes_at
                ):
                    raise ValueError("continuation trigger is outside canonical episode window")

                incoming_identity = (
                    token_mint,
                    trigger_kind,
                    direction,
                    chain_time,
                    method_version,
                    venue,
                )
                existing = conn.execute(
                    """SELECT episode_key, token_mint, trigger_kind, direction,
                        chain_time, observed_at, method_version, venue
                    FROM market_opportunity_episode_triggers
                    WHERE acquisition_run_key=? AND trigger_key=?""",
                    (run_key, trigger_key),
                ).fetchone()
                if existing is not None:
                    stored_venue = existing["venue"] if existing["venue"] is None else str(existing["venue"])
                    stored_identity = (
                        str(existing["token_mint"]),
                        str(existing["trigger_kind"]),
                        str(existing["direction"]),
                        int(existing["chain_time"]),
                        str(existing["method_version"]),
                        stored_venue,
                    )
                    stored_observed_at = int(existing["observed_at"])
                    if (
                        str(existing["episode_key"]) != episode_key
                        or stored_identity != incoming_identity
                    ):
                        _record_trigger_conflict(
                            conn,
                            acquisition_run_key=run_key,
                            trigger_key=trigger_key,
                            episode_key=str(existing["episode_key"]),
                            stored_observed_at=stored_observed_at,
                            incoming_observed_at=observed_at,
                            stored_identity=stored_identity,
                            incoming_identity=incoming_identity,
                            canonical_action="retain_first_persisted_trigger",
                        )
                        conflicts += 1
                    elif observed_at < stored_observed_at:
                        _record_trigger_conflict(
                            conn,
                            acquisition_run_key=run_key,
                            trigger_key=trigger_key,
                            episode_key=episode_key,
                            stored_observed_at=stored_observed_at,
                            incoming_observed_at=observed_at,
                            stored_identity=stored_identity,
                            incoming_identity=incoming_identity,
                            canonical_action="retain_first_persisted_trigger_earlier_replay",
                        )
                        conflicts += 1
                    continue

                conn.execute(
                    """INSERT INTO market_opportunity_episode_triggers(
                        acquisition_run_key, episode_key, trigger_key, token_mint,
                        trigger_kind, direction, chain_time, observed_at,
                        method_version, venue
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_key,
                        episode_key,
                        trigger_key,
                        token_mint,
                        trigger_kind,
                        direction,
                        chain_time,
                        observed_at,
                        method_version,
                        venue,
                    ),
                )
                inserted += 1

        attempted = len(items)
        return MarketContinuationTriggerBatchResultV0(
            attempted=attempted,
            inserted=inserted,
            replayed=attempted - inserted,
            conflicts=conflicts,
        )

    return _run_with_sqlite_lock_retry(persist_once)
