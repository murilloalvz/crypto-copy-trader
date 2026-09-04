import asyncio
import time
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Callable

from src.market_observation_store import record_market_lifecycle, record_market_trade
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation
from src.market_transaction_view import load_market_trades_by_transaction
from src.pumpswap_asset_role import classify_pumpswap_opportunity_asset
from src.pumpswap_normalized_persistence import PumpSwapNormalizedPersistResult
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapPoolResolver


@dataclass(frozen=True)
class PumpSwapPersistenceV2Telemetry:
    resolver_and_normalize_seconds: float
    writer_queue_wait_seconds: float
    writer_service_seconds: float


@dataclass(frozen=True)
class _LifecycleWrite:
    event_key: str
    observation: MarketLifecycleObservation


@dataclass(frozen=True)
class _TradeWrite:
    event_key: str
    observation: MarketTradeObservation


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _persist_db_stage(
    *,
    acquisition_run_key: str,
    transaction_key: str,
    lifecycle_writes: tuple[_LifecycleWrite, ...],
    trade_writes: tuple[_TradeWrite, ...],
    submitted_perf_counter: float,
) -> tuple[int, int, int, tuple[str, ...], float, float]:
    """Run the SQLite write/readback stage in one explicit writer executor thread."""

    writer_started = time.perf_counter()
    newly_persisted_lifecycle = 0
    for item in lifecycle_writes:
        if record_market_lifecycle(
            acquisition_run_key=acquisition_run_key,
            event_key=item.event_key,
            source_provider="solana_logs_subscribe",
            observation=item.observation,
        ):
            newly_persisted_lifecycle += 1

    inserted = 0
    duplicates = 0
    for item in trade_writes:
        if record_market_trade(
            acquisition_run_key=acquisition_run_key,
            event_key=item.event_key,
            source_provider="solana_logs_subscribe",
            observation=item.observation,
        ):
            inserted += 1
        else:
            duplicates += 1

    canonical_rows = load_market_trades_by_transaction(
        acquisition_run_key=acquisition_run_key,
        transaction_key=transaction_key,
    )
    affected_tokens = tuple(
        sorted(
            {
                item.observation.token_mint
                for item in canonical_rows
                if item.observation.venue == "pumpswap"
            }
        )
    )
    writer_finished = time.perf_counter()
    return (
        newly_persisted_lifecycle,
        inserted,
        duplicates,
        affected_tokens,
        max(0.0, writer_started - submitted_perf_counter),
        max(0.0, writer_finished - writer_started),
    )


async def persist_pumpswap_notification_normalized_v2(
    notification: PumpSwapLogNotification,
    *,
    acquisition_run_key: str,
    resolver: PumpSwapPoolResolver,
    db_executor: Executor,
    telemetry_sink: Callable[[PumpSwapPersistenceV2Telemetry], None] | None = None,
) -> PumpSwapNormalizedPersistResult:
    """Persist normalized PumpSwap evidence without blocking the asyncio event loop on SQLite.

    Pool resolution and resolver cache mutation stay on the event loop exactly as before. The
    canonical market-observation writes plus transaction readback are dispatched to an explicit
    SQLite writer executor. A single-thread executor is recommended: SQLite has one writer, WAL
    lets this writer coexist with concurrent read-only radar preparation, and the event loop stays
    available to resume completed prepare futures.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    if resolver.acquisition_run_key != run_key:
        raise ValueError("PumpSwap resolver run key does not match persistence run key")

    normalize_started = time.perf_counter()
    lifecycle_writes: list[_LifecycleWrite] = []
    role_filtered_lifecycle = 0
    for event in notification.lifecycle_events:
        resolver.learn_from_create(event, observed_at=notification.observed_at)
        role = classify_pumpswap_opportunity_asset(
            base_mint=event.base_mint,
            quote_mint=event.quote_mint,
        )
        if role is None:
            role_filtered_lifecycle += 1
            continue
        lifecycle_writes.append(
            _LifecycleWrite(
                event_key=f"pumpswap-create-normalized:{notification.signature}:{event.event_index}",
                observation=MarketLifecycleObservation(
                    token_mint=role.opportunity_mint,
                    market_started_at=event.timestamp,
                    observed_at=notification.observed_at,
                    venue="pumpswap",
                ),
            )
        )

    trade_writes: list[_TradeWrite] = []
    unresolved = 0
    role_filtered = 0
    for event in notification.trade_events:
        mapping = await resolver.resolve(event.pool, as_of=notification.observed_at)
        if mapping is None:
            unresolved += 1
            continue

        role = classify_pumpswap_opportunity_asset(
            base_mint=mapping.base_mint,
            quote_mint=mapping.quote_mint,
        )
        if role is None:
            role_filtered += 1
            continue

        effective_observed_at = max(notification.observed_at, mapping.observed_at)
        normalized_side = role.normalize_event_side(event.side)
        trade_writes.append(
            _TradeWrite(
                event_key=f"pumpswap-normalized-{event.side}:{notification.signature}:{event.event_index}",
                observation=MarketTradeObservation(
                    token_mint=role.opportunity_mint,
                    side=normalized_side,
                    chain_time=event.timestamp,
                    observed_at=effective_observed_at,
                    wallet_address=event.user,
                    notional_usd=None,
                    price_usd=None,
                    venue="pumpswap",
                    transaction_key=notification.signature,
                ),
            )
        )

    writer_submitted = time.perf_counter()
    normalize_seconds = max(0.0, writer_submitted - normalize_started)
    loop = asyncio.get_running_loop()
    (
        newly_persisted_lifecycle,
        inserted,
        duplicates,
        affected_tokens,
        writer_queue_wait_seconds,
        writer_service_seconds,
    ) = await loop.run_in_executor(
        db_executor,
        lambda: _persist_db_stage(
            acquisition_run_key=run_key,
            transaction_key=notification.signature,
            lifecycle_writes=tuple(lifecycle_writes),
            trade_writes=tuple(trade_writes),
            submitted_perf_counter=writer_submitted,
        ),
    )

    if telemetry_sink is not None:
        telemetry_sink(
            PumpSwapPersistenceV2Telemetry(
                resolver_and_normalize_seconds=normalize_seconds,
                writer_queue_wait_seconds=writer_queue_wait_seconds,
                writer_service_seconds=writer_service_seconds,
            )
        )

    return PumpSwapNormalizedPersistResult(
        newly_persisted_trades=inserted,
        duplicate_or_replayed_trades=duplicates,
        unresolved_trades=unresolved,
        role_filtered_trades=role_filtered,
        newly_persisted_lifecycle=newly_persisted_lifecycle,
        role_filtered_lifecycle=role_filtered_lifecycle,
        affected_tokens=affected_tokens,
    )
