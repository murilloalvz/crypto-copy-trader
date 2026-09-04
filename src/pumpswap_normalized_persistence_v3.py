import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from src.database import connection
from src.market_observation_store import (
    _choose_conflict_action,
    _record_replay_conflict,
    _required as _store_required,
    _validate_lifecycle,
    _validate_trade,
    ensure_market_observation_schema,
)
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation
from src.pumpswap_asset_role import classify_pumpswap_opportunity_asset
from src.pumpswap_normalized_persistence import PumpSwapNormalizedPersistResult
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapPoolResolver


_SOURCE_PROVIDER = "solana_logs_subscribe"
_SENTINEL = object()


@dataclass(frozen=True)
class _LifecycleWrite:
    event_key: str
    observation: MarketLifecycleObservation


@dataclass(frozen=True)
class _TradeWrite:
    event_key: str
    observation: MarketTradeObservation


@dataclass(frozen=True)
class PreparedPumpSwapPersistenceV3:
    acquisition_run_key: str
    transaction_key: str
    lifecycle_writes: tuple[_LifecycleWrite, ...]
    trade_writes: tuple[_TradeWrite, ...]
    unresolved_trades: int
    role_filtered_trades: int
    role_filtered_lifecycle: int
    resolver_and_normalize_seconds: float


@dataclass(frozen=True)
class PumpSwapPersistenceV3Telemetry:
    resolver_and_normalize_seconds: float
    writer_queue_wait_seconds: float
    writer_batch_service_seconds: float
    writer_result_wait_seconds: float
    writer_batch_size: int


@dataclass
class _BatchRequest:
    prepared: PreparedPumpSwapPersistenceV3
    submitted_perf_counter: float
    future: asyncio.Future


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


async def prepare_pumpswap_notification_normalized_v3(
    notification: PumpSwapLogNotification,
    *,
    acquisition_run_key: str,
    resolver: PumpSwapPoolResolver,
) -> PreparedPumpSwapPersistenceV3:
    """Resolve/normalize one notification without performing market-observation SQLite writes."""

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    if resolver.acquisition_run_key != run_key:
        raise ValueError("PumpSwap resolver run key does not match persistence run key")

    started = time.perf_counter()
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
                event_key=(
                    f"pumpswap-create-normalized:{notification.signature}:{event.event_index}"
                ),
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
        trade_writes.append(
            _TradeWrite(
                event_key=(
                    f"pumpswap-normalized-{event.side}:"
                    f"{notification.signature}:{event.event_index}"
                ),
                observation=MarketTradeObservation(
                    token_mint=role.opportunity_mint,
                    side=role.normalize_event_side(event.side),
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

    return PreparedPumpSwapPersistenceV3(
        acquisition_run_key=run_key,
        transaction_key=_required(notification.signature, "notification.signature"),
        lifecycle_writes=tuple(lifecycle_writes),
        trade_writes=tuple(trade_writes),
        unresolved_trades=unresolved,
        role_filtered_trades=role_filtered,
        role_filtered_lifecycle=role_filtered_lifecycle,
        resolver_and_normalize_seconds=max(0.0, time.perf_counter() - started),
    )


def _record_lifecycle_with_connection(conn, *, run_key: str, item: _LifecycleWrite) -> bool:
    raw_key = _store_required(item.event_key, "event_key")
    observation = item.observation
    _validate_lifecycle(observation)
    identity_values = (
        _SOURCE_PROVIDER,
        observation.token_mint,
        observation.market_started_at,
        observation.venue,
    )
    existing = conn.execute(
        """SELECT source_provider, token_mint, market_started_at, observed_at, venue
        FROM market_lifecycle_observations
        WHERE acquisition_run_key=? AND event_key=?""",
        (run_key, raw_key),
    ).fetchone()
    if existing is not None:
        existing_identity = tuple(
            existing[key]
            for key in ("source_provider", "token_mint", "market_started_at", "venue")
        )
        stored_observed_at = int(existing["observed_at"])
        incoming_observed_at = int(observation.observed_at)
        if existing_identity == identity_values:
            if incoming_observed_at < stored_observed_at:
                conn.execute(
                    """UPDATE market_lifecycle_observations SET observed_at=?
                    WHERE acquisition_run_key=? AND event_key=?""",
                    (incoming_observed_at, run_key, raw_key),
                )
            return False

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
            source_provider=_SOURCE_PROVIDER,
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
                    _SOURCE_PROVIDER,
                    observation.token_mint,
                    observation.market_started_at,
                    incoming_observed_at,
                    observation.venue,
                    run_key,
                    raw_key,
                ),
            )
        return False

    conn.execute(
        """INSERT INTO market_lifecycle_observations(
            acquisition_run_key, event_key, source_provider, token_mint,
            market_started_at, observed_at, venue
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            run_key,
            raw_key,
            _SOURCE_PROVIDER,
            observation.token_mint,
            observation.market_started_at,
            observation.observed_at,
            observation.venue,
        ),
    )
    return True


def _record_trade_with_connection(conn, *, run_key: str, item: _TradeWrite) -> bool:
    raw_key = _store_required(item.event_key, "event_key")
    observation = item.observation
    _validate_trade(observation)
    identity_values = (
        _SOURCE_PROVIDER,
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
        existing_identity = tuple(
            existing[key]
            for key in (
                "source_provider",
                "token_mint",
                "side",
                "chain_time",
                "wallet_address",
                "notional_usd",
                "price_usd",
                "venue",
                "transaction_key",
            )
        )
        stored_observed_at = int(existing["observed_at"])
        incoming_observed_at = int(observation.observed_at)
        if existing_identity == identity_values:
            if incoming_observed_at < stored_observed_at:
                conn.execute(
                    """UPDATE market_trade_observations SET observed_at=?
                    WHERE acquisition_run_key=? AND event_key=?""",
                    (incoming_observed_at, run_key, raw_key),
                )
            return False

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
            source_provider=_SOURCE_PROVIDER,
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
                    _SOURCE_PROVIDER,
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

    conn.execute(
        """INSERT INTO market_trade_observations(
            acquisition_run_key, event_key, source_provider, token_mint, side,
            chain_time, observed_at, wallet_address, notional_usd, price_usd, venue,
            transaction_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_key,
            raw_key,
            _SOURCE_PROVIDER,
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
    return True


def _persist_prepared_batch_db_stage(
    prepared_items: tuple[PreparedPumpSwapPersistenceV3, ...],
) -> tuple[tuple[PumpSwapNormalizedPersistResult, ...], float, float]:
    """Persist a batch in one SQLite transaction while preserving per-item replay semantics."""

    if not prepared_items:
        return (), time.perf_counter(), time.perf_counter()
    ensure_market_observation_schema()
    writer_started = time.perf_counter()
    results: list[PumpSwapNormalizedPersistResult] = []
    with connection() as conn:
        for prepared in prepared_items:
            newly_persisted_lifecycle = 0
            for item in prepared.lifecycle_writes:
                if _record_lifecycle_with_connection(
                    conn,
                    run_key=prepared.acquisition_run_key,
                    item=item,
                ):
                    newly_persisted_lifecycle += 1

            inserted = 0
            duplicates = 0
            for item in prepared.trade_writes:
                if _record_trade_with_connection(
                    conn,
                    run_key=prepared.acquisition_run_key,
                    item=item,
                ):
                    inserted += 1
                else:
                    duplicates += 1

            rows = conn.execute(
                """SELECT token_mint
                FROM market_trade_observations
                WHERE acquisition_run_key=? AND transaction_key=? AND venue='pumpswap'
                ORDER BY token_mint, id""",
                (prepared.acquisition_run_key, prepared.transaction_key),
            ).fetchall()
            affected_tokens = tuple(sorted({str(row["token_mint"]) for row in rows}))
            results.append(
                PumpSwapNormalizedPersistResult(
                    newly_persisted_trades=inserted,
                    duplicate_or_replayed_trades=duplicates,
                    unresolved_trades=prepared.unresolved_trades,
                    role_filtered_trades=prepared.role_filtered_trades,
                    newly_persisted_lifecycle=newly_persisted_lifecycle,
                    role_filtered_lifecycle=prepared.role_filtered_lifecycle,
                    affected_tokens=affected_tokens,
                )
            )
    writer_finished = time.perf_counter()
    return tuple(results), writer_started, writer_finished


class PumpSwapSQLiteMicrobatchWriter:
    """One WAL writer thread with bounded microbatching and per-request async results."""

    def __init__(
        self,
        *,
        batch_size: int = 32,
        max_wait_ms: int = 10,
        telemetry_sink: Callable[[PumpSwapPersistenceV3Telemetry], None] | None = None,
    ):
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if max_wait_ms < 0:
            raise ValueError("max_wait_ms cannot be negative")
        self.batch_size = int(batch_size)
        self.max_wait_seconds = float(max_wait_ms) / 1000.0
        self.telemetry_sink = telemetry_sink
        self.batch_sizes: list[int] = []
        self.batch_service_seconds: list[float] = []
        self._queue: asyncio.Queue = asyncio.Queue()
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="pumpswap-sqlite-microbatch-writer",
        )
        self._task: asyncio.Task | None = None
        self._closing = False

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="pumpswap-sqlite-microbatch-writer")

    async def submit(
        self,
        prepared: PreparedPumpSwapPersistenceV3,
    ) -> PumpSwapNormalizedPersistResult:
        if self._closing:
            raise RuntimeError("PumpSwap SQLite microbatch writer is closing")
        await self.start()
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self._queue.put(
            _BatchRequest(
                prepared=prepared,
                submitted_perf_counter=time.perf_counter(),
                future=future,
            )
        )
        return await future

    async def close(self, *, cancel_pending: bool = True) -> None:
        if self._closing:
            if self._task is not None:
                await self._task
            return
        self._closing = True
        if cancel_pending:
            while True:
                try:
                    item = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item is not _SENTINEL and not item.future.done():
                    item.future.cancel()
                self._queue.task_done()
        await self._queue.put(_SENTINEL)
        if self._task is not None:
            await self._task
        self._executor.shutdown(wait=True, cancel_futures=True)

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        stop_after_batch = False
        while True:
            first = await self._queue.get()
            if first is _SENTINEL:
                self._queue.task_done()
                break

            batch: list[_BatchRequest] = [first]
            collect_started = loop.time()
            stop_after_batch = False
            while len(batch) < self.batch_size:
                try:
                    item = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    remaining = self.max_wait_seconds - (loop.time() - collect_started)
                    if remaining <= 0:
                        break
                    try:
                        item = await asyncio.wait_for(self._queue.get(), timeout=remaining)
                    except asyncio.TimeoutError:
                        break

                if item is _SENTINEL:
                    self._queue.task_done()
                    stop_after_batch = True
                    break
                batch.append(item)

            try:
                results, writer_started, writer_finished = await loop.run_in_executor(
                    self._executor,
                    _persist_prepared_batch_db_stage,
                    tuple(item.prepared for item in batch),
                )
                if len(results) != len(batch):
                    raise RuntimeError("PumpSwap writer batch result count does not match input count")
                batch_service = max(0.0, writer_finished - writer_started)
                self.batch_sizes.append(len(batch))
                self.batch_service_seconds.append(batch_service)
                for request, result in zip(batch, results):
                    if self.telemetry_sink is not None:
                        self.telemetry_sink(
                            PumpSwapPersistenceV3Telemetry(
                                resolver_and_normalize_seconds=(
                                    request.prepared.resolver_and_normalize_seconds
                                ),
                                writer_queue_wait_seconds=max(
                                    0.0,
                                    writer_started - request.submitted_perf_counter,
                                ),
                                writer_batch_service_seconds=batch_service,
                                writer_result_wait_seconds=max(
                                    0.0,
                                    writer_finished - request.submitted_perf_counter,
                                ),
                                writer_batch_size=len(batch),
                            )
                        )
                    if not request.future.done():
                        request.future.set_result(result)
            except Exception as exc:
                for request in batch:
                    if not request.future.done():
                        request.future.set_exception(exc)
            finally:
                for _ in batch:
                    self._queue.task_done()

            if stop_after_batch:
                break


async def persist_pumpswap_notification_normalized_v3(
    notification: PumpSwapLogNotification,
    *,
    acquisition_run_key: str,
    resolver: PumpSwapPoolResolver,
    writer: PumpSwapSQLiteMicrobatchWriter,
) -> PumpSwapNormalizedPersistResult:
    prepared = await prepare_pumpswap_notification_normalized_v3(
        notification,
        acquisition_run_key=acquisition_run_key,
        resolver=resolver,
    )
    return await writer.submit(prepared)
