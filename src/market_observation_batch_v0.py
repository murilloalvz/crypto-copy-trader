from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.database import connection
from src.market_observation_store import (
    _choose_conflict_action,
    _record_replay_conflict,
    _required,
    _validate_lifecycle,
    _validate_trade,
    ensure_market_observation_schema,
)
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation


@dataclass(frozen=True)
class MarketTradeWriteV0:
    acquisition_run_key: str
    event_key: str
    source_provider: str
    observation: MarketTradeObservation


@dataclass(frozen=True)
class MarketLifecycleWriteV0:
    acquisition_run_key: str
    event_key: str
    source_provider: str
    observation: MarketLifecycleObservation


MarketObservationWriteV0 = MarketTradeWriteV0 | MarketLifecycleWriteV0


@dataclass(frozen=True)
class MarketObservationBatchResultV0:
    attempted: int
    inserted: int
    replayed: int
    conflicts: int


def _record_trade_conn(conn, item: MarketTradeWriteV0) -> tuple[bool, bool]:
    run_key = _required(item.acquisition_run_key, "acquisition_run_key")
    raw_key = _required(item.event_key, "event_key")
    provider = _required(item.source_provider, "source_provider")
    observation = item.observation
    _validate_trade(observation)
    identity_values = (
        provider,
        observation.token_mint,
        observation.side,
        observation.chain_time,
        observation.wallet_address,
        observation.notional_usd,
        observation.price_usd,
        observation.venue,
        observation.transaction_key,
    )
    existing = conn.execute(
        """SELECT source_provider, token_mint, side, chain_time, observed_at,
            wallet_address, notional_usd, price_usd, venue, transaction_key
        FROM market_trade_observations
        WHERE acquisition_run_key=? AND event_key=?""",
        (run_key, raw_key),
    ).fetchone()
    if existing is not None:
        existing_identity = tuple(existing[key] for key in (
            "source_provider", "token_mint", "side", "chain_time",
            "wallet_address", "notional_usd", "price_usd", "venue", "transaction_key"
        ))
        stored_observed_at = int(existing["observed_at"])
        incoming_observed_at = int(observation.observed_at)
        if existing_identity == identity_values:
            if incoming_observed_at < stored_observed_at:
                conn.execute(
                    "UPDATE market_trade_observations SET observed_at=? WHERE acquisition_run_key=? AND event_key=?",
                    (incoming_observed_at, run_key, raw_key),
                )
            return False, False
        action, incoming_wins = _choose_conflict_action(
            stored_observed_at=stored_observed_at,
            incoming_observed_at=incoming_observed_at,
            stored_identity=existing_identity,
            incoming_identity=identity_values,
        )
        _record_replay_conflict(
            conn,
            acquisition_run_key=run_key,
            event_key=raw_key,
            event_type="trade",
            source_provider=provider,
            stored_observed_at=stored_observed_at,
            incoming_observed_at=incoming_observed_at,
            stored_identity=existing_identity,
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
                    provider, observation.token_mint, observation.side, observation.chain_time,
                    incoming_observed_at, observation.wallet_address, observation.notional_usd,
                    observation.price_usd, observation.venue, observation.transaction_key,
                    run_key, raw_key,
                ),
            )
        return False, True
    conn.execute(
        """INSERT INTO market_trade_observations(
            acquisition_run_key, event_key, source_provider, token_mint, side,
            chain_time, observed_at, wallet_address, notional_usd, price_usd, venue,
            transaction_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_key, raw_key, provider, observation.token_mint, observation.side,
            observation.chain_time, observation.observed_at, observation.wallet_address,
            observation.notional_usd, observation.price_usd, observation.venue,
            observation.transaction_key,
        ),
    )
    return True, False


def _record_lifecycle_conn(conn, item: MarketLifecycleWriteV0) -> tuple[bool, bool]:
    run_key = _required(item.acquisition_run_key, "acquisition_run_key")
    raw_key = _required(item.event_key, "event_key")
    provider = _required(item.source_provider, "source_provider")
    observation = item.observation
    _validate_lifecycle(observation)
    identity_values = (provider, observation.token_mint, observation.market_started_at, observation.venue)
    existing = conn.execute(
        """SELECT source_provider, token_mint, market_started_at, observed_at, venue
        FROM market_lifecycle_observations
        WHERE acquisition_run_key=? AND event_key=?""",
        (run_key, raw_key),
    ).fetchone()
    if existing is not None:
        existing_identity = tuple(existing[key] for key in (
            "source_provider", "token_mint", "market_started_at", "venue"
        ))
        stored_observed_at = int(existing["observed_at"])
        incoming_observed_at = int(observation.observed_at)
        if existing_identity == identity_values:
            if incoming_observed_at < stored_observed_at:
                conn.execute(
                    "UPDATE market_lifecycle_observations SET observed_at=? WHERE acquisition_run_key=? AND event_key=?",
                    (incoming_observed_at, run_key, raw_key),
                )
            return False, False
        action, incoming_wins = _choose_conflict_action(
            stored_observed_at=stored_observed_at,
            incoming_observed_at=incoming_observed_at,
            stored_identity=existing_identity,
            incoming_identity=identity_values,
        )
        _record_replay_conflict(
            conn,
            acquisition_run_key=run_key,
            event_key=raw_key,
            event_type="lifecycle",
            source_provider=provider,
            stored_observed_at=stored_observed_at,
            incoming_observed_at=incoming_observed_at,
            stored_identity=existing_identity,
            incoming_identity=identity_values,
            canonical_action=action,
        )
        if incoming_wins:
            conn.execute(
                """UPDATE market_lifecycle_observations
                SET source_provider=?, token_mint=?, market_started_at=?, observed_at=?, venue=?
                WHERE acquisition_run_key=? AND event_key=?""",
                (
                    provider, observation.token_mint, observation.market_started_at,
                    incoming_observed_at, observation.venue, run_key, raw_key,
                ),
            )
        return False, True
    conn.execute(
        """INSERT INTO market_lifecycle_observations(
            acquisition_run_key, event_key, source_provider, token_mint,
            market_started_at, observed_at, venue
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            run_key, raw_key, provider, observation.token_mint,
            observation.market_started_at, observation.observed_at, observation.venue,
        ),
    )
    return True, False


def record_market_observations_batch_v0(
    items: Sequence[MarketObservationWriteV0],
) -> MarketObservationBatchResultV0:
    """Persist observation writes in input order using one SQLite transaction.

    Replay/conflict semantics intentionally match market_observation_store's single-row
    APIs. The function is designed for the Durable/Research Plane, never the signal hot path.
    """
    if not items:
        return MarketObservationBatchResultV0(attempted=0, inserted=0, replayed=0, conflicts=0)
    ensure_market_observation_schema()
    inserted = 0
    conflicts = 0
    with connection() as conn:
        for item in items:
            if isinstance(item, MarketTradeWriteV0):
                was_inserted, was_conflict = _record_trade_conn(conn, item)
            elif isinstance(item, MarketLifecycleWriteV0):
                was_inserted, was_conflict = _record_lifecycle_conn(conn, item)
            else:
                raise TypeError(f"unsupported market observation write: {type(item).__name__}")
            inserted += int(was_inserted)
            conflicts += int(was_conflict)
    attempted = len(items)
    return MarketObservationBatchResultV0(
        attempted=attempted,
        inserted=inserted,
        replayed=attempted - inserted,
        conflicts=conflicts,
    )
