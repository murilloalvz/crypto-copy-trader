from __future__ import annotations

import asyncio
from concurrent.futures import Future
from dataclasses import dataclass
import queue
import threading
import time

from src.database import connection
from src.market_opportunity_episode_store import (
    MarketOpportunityEpisode,
    _load_episode_row,
    _record_trigger_conflict,
    _row_to_episode,
    ensure_market_opportunity_episode_schema,
)


_SENTINEL = object()
_RETAIN_FIRST_PERSISTED_TRIGGER = "retain_first_persisted_trigger"
_RETAIN_FIRST_PERSISTED_TRIGGER_EARLIER_REPLAY = (
    "retain_first_persisted_trigger_earlier_replay"
)


@dataclass(frozen=True)
class ContinuationTriggerRecord:
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
class ContinuationWriterTelemetry:
    queue_wait_seconds: float
    batch_service_seconds: float
    result_wait_seconds: float
    batch_size: int


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _validate_record(record: ContinuationTriggerRecord) -> None:
    _required(record.acquisition_run_key, "acquisition_run_key")
    _required(record.episode_key, "episode_key")
    _required(record.trigger_key, "trigger_key")
    _required(record.token_mint, "token_mint")
    _required(record.trigger_kind, "trigger_kind")
    _required(record.direction, "direction")
    _required(record.method_version, "method_version")
    if record.venue is not None:
        _required(record.venue, "venue")
    if record.chain_time < 0 or record.observed_at < 0:
        raise ValueError("trigger timestamps must be non-negative")
    if record.observed_at < record.chain_time:
        raise ValueError("trigger observed_at cannot precede chain_time")


def _identity(record: ContinuationTriggerRecord) -> tuple:
    return (
        record.token_mint,
        record.trigger_kind,
        record.direction,
        int(record.chain_time),
        record.method_version,
        record.venue,
    )


def _stored_identity(row) -> tuple:
    venue = row["venue"] if row["venue"] is None else str(row["venue"])
    return (
        str(row["token_mint"]),
        str(row["trigger_kind"]),
        str(row["direction"]),
        int(row["chain_time"]),
        str(row["method_version"]),
        venue,
    )


def _validate_expected_episode(
    episode: MarketOpportunityEpisode,
    record: ContinuationTriggerRecord,
) -> None:
    if episode.acquisition_run_key != record.acquisition_run_key:
        raise RuntimeError("continuation trigger episode belongs to another acquisition run")
    if episode.token_mint != record.token_mint:
        raise RuntimeError("continuation trigger token does not match canonical episode")
    if not (
        episode.first_trigger_observed_at
        <= record.observed_at
        < episode.episode_closes_at
    ):
        raise RuntimeError("continuation trigger is outside the canonical episode window")


def _persist_continuation_batch_db_stage(
    records: tuple[ContinuationTriggerRecord, ...],
) -> tuple[tuple[MarketOpportunityEpisode, ...], float, float]:
    """Append already-classified continuation triggers in one SQLite transaction.

    This function never opens or reshapes an episode. The caller must provide an already
    persisted canonical episode whose window contains the trigger. Exact trigger replay is
    idempotent and conflicting replay keeps the first persisted trigger canonical, matching
    ``assign_market_opportunity_trigger`` semantics.
    """

    if not records:
        now = time.perf_counter()
        return (), now, now
    for record in records:
        _validate_record(record)
    ensure_market_opportunity_episode_schema()

    writer_started = time.perf_counter()
    results: list[MarketOpportunityEpisode] = []
    with connection() as conn:
        for record in records:
            expected_row = _load_episode_row(conn, record.episode_key)
            if expected_row is None:
                raise RuntimeError("continuation trigger references missing canonical episode")
            expected_episode = _row_to_episode(expected_row)
            _validate_expected_episode(expected_episode, record)

            cursor = conn.execute(
                """INSERT OR IGNORE INTO market_opportunity_episode_triggers(
                    acquisition_run_key, episode_key, trigger_key, token_mint,
                    trigger_kind, direction, chain_time, observed_at,
                    method_version, venue
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.acquisition_run_key,
                    record.episode_key,
                    record.trigger_key,
                    record.token_mint,
                    record.trigger_kind,
                    record.direction,
                    int(record.chain_time),
                    int(record.observed_at),
                    record.method_version,
                    record.venue,
                ),
            )
            if cursor.rowcount == 1:
                results.append(expected_episode)
                continue

            existing = conn.execute(
                """SELECT episode_key, token_mint, trigger_kind, direction,
                    chain_time, observed_at, method_version, venue
                FROM market_opportunity_episode_triggers
                WHERE acquisition_run_key=? AND trigger_key=?""",
                (record.acquisition_run_key, record.trigger_key),
            ).fetchone()
            if existing is None:
                raise RuntimeError("continuation trigger INSERT OR IGNORE lost canonical row")

            stored_episode_key = str(existing["episode_key"])
            stored_episode_row = _load_episode_row(conn, stored_episode_key)
            if stored_episode_row is None:
                raise RuntimeError("persisted continuation trigger references missing episode")
            stored_episode = _row_to_episode(stored_episode_row)
            stored_identity = _stored_identity(existing)
            incoming_identity = _identity(record)
            stored_observed_at = int(existing["observed_at"])

            if stored_identity != incoming_identity:
                _record_trigger_conflict(
                    conn,
                    acquisition_run_key=record.acquisition_run_key,
                    trigger_key=record.trigger_key,
                    episode_key=stored_episode_key,
                    stored_observed_at=stored_observed_at,
                    incoming_observed_at=record.observed_at,
                    stored_identity=stored_identity,
                    incoming_identity=incoming_identity,
                    canonical_action=_RETAIN_FIRST_PERSISTED_TRIGGER,
                )
            elif record.observed_at < stored_observed_at:
                _record_trigger_conflict(
                    conn,
                    acquisition_run_key=record.acquisition_run_key,
                    trigger_key=record.trigger_key,
                    episode_key=stored_episode_key,
                    stored_observed_at=stored_observed_at,
                    incoming_observed_at=record.observed_at,
                    stored_identity=stored_identity,
                    incoming_identity=incoming_identity,
                    canonical_action=_RETAIN_FIRST_PERSISTED_TRIGGER_EARLIER_REPLAY,
                )
            results.append(stored_episode)

    writer_finished = time.perf_counter()
    return tuple(results), writer_started, writer_finished


class MarketTriggerContinuationWriter:
    """Thread-owned microbatch writer for append-only continuation trigger audit rows.

    Episode opening remains on the causal stateful path. Once an episode is already
    canonical, later detector-positive notifications do not need to block causal result
    availability on one SQLite transaction per notification. They are appended here in
    ordered microbatches, preserving exact-replay/conflict audit semantics while reducing
    writer-lock acquisitions.
    """

    def __init__(self, *, batch_size: int = 32, max_wait_ms: int = 5):
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if max_wait_ms < 0:
            raise ValueError("max_wait_ms cannot be negative")
        self.batch_size = int(batch_size)
        self.max_wait_seconds = float(max_wait_ms) / 1000.0
        self.batch_sizes: list[int] = []
        self.batch_service_seconds: list[float] = []
        self.queue_wait_seconds: list[float] = []
        self.result_wait_seconds: list[float] = []
        self._queue: queue.Queue = queue.Queue()
        self._closing = False
        self._lock = threading.Lock()
        self._fatal_exception: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="market-trigger-continuation-writer",
            daemon=True,
        )
        self._thread.start()

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def fatal_exception(self) -> BaseException | None:
        return self._fatal_exception

    def enqueue(self, record: ContinuationTriggerRecord) -> Future:
        _validate_record(record)
        with self._lock:
            if self._closing:
                raise RuntimeError("market trigger continuation writer is closing")
            if self._fatal_exception is not None:
                raise RuntimeError("market trigger continuation writer previously failed") from self._fatal_exception
            future: Future = Future()
            self._queue.put_nowait((record, time.perf_counter(), future))
            return future

    async def submit(self, record: ContinuationTriggerRecord) -> MarketOpportunityEpisode:
        return await asyncio.wrap_future(self.enqueue(record))

    async def close(self, *, cancel_pending: bool = False) -> None:
        with self._lock:
            if self._closing:
                already_closing = True
            else:
                self._closing = True
                already_closing = False
        if not already_closing:
            if cancel_pending:
                while True:
                    try:
                        item = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if item is _SENTINEL:
                        self._queue.task_done()
                        continue
                    _, _, future = item
                    future.cancel()
                    self._queue.task_done()
            self._queue.put_nowait(_SENTINEL)
        if self._thread.is_alive():
            await asyncio.to_thread(self._thread.join)
        if self._fatal_exception is not None:
            raise RuntimeError("market trigger continuation writer failed") from self._fatal_exception

    def _run(self) -> None:
        stop_after_batch = False
        while True:
            first = self._queue.get()
            if first is _SENTINEL:
                self._queue.task_done()
                break

            batch = [first]
            collect_started = time.perf_counter()
            stop_after_batch = False
            while len(batch) < self.batch_size:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    remaining = self.max_wait_seconds - (
                        time.perf_counter() - collect_started
                    )
                    if remaining <= 0:
                        break
                    try:
                        item = self._queue.get(timeout=remaining)
                    except queue.Empty:
                        break
                if item is _SENTINEL:
                    self._queue.task_done()
                    stop_after_batch = True
                    break
                batch.append(item)

            try:
                records = tuple(item[0] for item in batch)
                results, writer_started, writer_finished = _persist_continuation_batch_db_stage(
                    records
                )
                if len(results) != len(batch):
                    raise RuntimeError("continuation writer batch result count mismatch")
                batch_service = max(0.0, writer_finished - writer_started)
                self.batch_sizes.append(len(batch))
                self.batch_service_seconds.append(batch_service)
                for request, result in zip(batch, results):
                    _, submitted_at, future = request
                    self.queue_wait_seconds.append(
                        max(0.0, writer_started - submitted_at)
                    )
                    self.result_wait_seconds.append(
                        max(0.0, writer_finished - submitted_at)
                    )
                    if not future.done():
                        future.set_result(result)
            except BaseException as exc:
                self._fatal_exception = exc
                for _, _, future in batch:
                    if not future.done():
                        future.set_exception(exc)
            finally:
                for _ in batch:
                    self._queue.task_done()

            if stop_after_batch:
                break
