import argparse
import asyncio
import hashlib
import threading
import time
from collections import Counter
from dataclasses import dataclass

from src.config import settings
from src.opportunity_enrichment_store import admit_opportunity_episode
from src.opportunity_episode_enrichment import build_episode_enrichment_bundle
from src.pump_batch_persistence import PumpBatchPersistResult, persist_pump_notification_batch
from src.pump_bonding_stream import iter_pump_log_notifications
from src.pump_microbatch_persistence import persist_pump_notifications_microbatch
from src.pump_radar_bridge_v4 import evaluate_persisted_pump_notification_for_radar_v4
from src.pumpswap_asset_role import REFERENCE_ASSET_MINTS_V1
from src.pumpswap_concurrent_resolver import ConcurrentReusablePumpSwapPoolResolver
from src.pumpswap_normalized_persistence import (
    PumpSwapNormalizedPersistResult,
    persist_pumpswap_notification_normalized,
)
from src.pumpswap_radar_bridge_v3 import evaluate_persisted_pumpswap_notification_for_radar_v3
from src.pumpswap_stream import iter_pumpswap_log_notifications
from src.solana import SolanaRPCError


MAX_SMOKE_SECONDS = 900


@dataclass(frozen=True)
class QueuedNotification:
    sequence: int
    notification: object
    enqueued_monotonic: float


@dataclass(frozen=True)
class CompletedPumpNotification:
    sequence: int
    notification: object
    persist_result: PumpBatchPersistResult
    enqueued_monotonic: float


@dataclass(frozen=True)
class CompletedPumpSwapNotification:
    sequence: int
    notification: object
    persist_result: PumpSwapNormalizedPersistResult
    enqueued_monotonic: float


class BoundedConcurrentResolver(ConcurrentReusablePumpSwapPoolResolver):
    def __init__(self, *args, max_network_hydrations: int, retry_seconds: float = 15.0, **kwargs):
        if max_network_hydrations <= 0:
            raise ValueError("max_network_hydrations must be positive")
        super().__init__(*args, **kwargs)
        self.max_network_hydrations = int(max_network_hydrations)
        self.retry_seconds = float(retry_seconds)
        self.network_hydration_calls = 0
        self.hydration_budget_skips = 0
        self.negative_cache_skips = 0
        self._failed_until: dict[str, float] = {}
        self._budget_lock = threading.Lock()

    def _load_pool_account(self, pool_address: str):
        now = time.monotonic()
        with self._budget_lock:
            retry_at = self._failed_until.get(pool_address)
            if retry_at is not None and now < retry_at:
                self.negative_cache_skips += 1
                raise ValueError("negative-cache skip")
            if self.network_hydration_calls >= self.max_network_hydrations:
                self.hydration_budget_skips += 1
                raise ValueError("hydration budget exhausted")
            self.network_hydration_calls += 1
        try:
            result = super()._load_pool_account(pool_address)
        except (SolanaRPCError, ValueError, TypeError, KeyError):
            with self._budget_lock:
                self._failed_until[pool_address] = now + self.retry_seconds
            raise
        with self._budget_lock:
            if result is None:
                self._failed_until[pool_address] = now + self.retry_seconds
            else:
                self._failed_until.pop(pool_address, None)
        return result


def _short_episode(episode_key: str) -> str:
    return hashlib.sha256(episode_key.encode("utf-8")).hexdigest()[:10]


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def _latency_summary_ms(values: list[float]) -> str:
    if not values:
        return "p50=0.0 p95=0.0 max=0.0"
    return (
        f"p50={_percentile(values, 0.50) * 1000:.1f} "
        f"p95={_percentile(values, 0.95) * 1000:.1f} "
        f"max={max(values) * 1000:.1f}"
    )


async def run_smoke(
    *,
    run_key: str,
    duration_seconds: int,
    commitment: str,
    max_hydrations: int,
    rpc_timeout_seconds: int,
    pump_workers: int,
    pumpswap_workers: int,
    max_concurrent_resolutions: int,
    queue_size: int,
    pump_microbatch_size: int = 1,
    pump_microbatch_max_wait_ms: int = 0,
) -> None:
    if pump_microbatch_size <= 0:
        raise ValueError("pump_microbatch_size must be positive")
    if pump_microbatch_max_wait_ms < 0:
        raise ValueError("pump_microbatch_max_wait_ms cannot be negative")

    started = time.monotonic()
    deadline = started + duration_seconds

    pump_queue: asyncio.Queue[QueuedNotification] = asyncio.Queue(maxsize=queue_size)
    pump_completed: asyncio.Queue[CompletedPumpNotification] = asyncio.Queue()
    pumpswap_queue: asyncio.Queue[QueuedNotification] = asyncio.Queue(maxsize=queue_size)
    pumpswap_completed: asyncio.Queue[CompletedPumpSwapNotification] = asyncio.Queue()

    resolver = BoundedConcurrentResolver(
        acquisition_run_key=run_key,
        commitment=commitment,
        rpc_url=settings.rpc_url,
        fallback_urls=settings.rpc_fallback_urls,
        timeout=rpc_timeout_seconds,
        max_network_hydrations=max_hydrations,
        max_concurrent_resolutions=max_concurrent_resolutions,
    )

    received: Counter[str] = Counter()
    enqueued: Counter[str] = Counter()
    dropped: Counter[str] = Counter()
    persistence_completed: Counter[str] = Counter()
    radar_processed: Counter[str] = Counter()
    persisted_trades: Counter[str] = Counter()
    hits_by_source: Counter[str] = Counter()
    episodes_by_source: Counter[str] = Counter()
    queue_high_water: Counter[str] = Counter()
    worker_errors: Counter[str] = Counter()
    affected_tokens: set[str] = set()
    episodes_seen: set[str] = set()
    pending_pump: dict[int, CompletedPumpNotification] = {}
    pending_pumpswap: dict[int, CompletedPumpSwapNotification] = {}
    pump_persist_wait_seconds: list[float] = []
    pump_radar_wait_seconds: list[float] = []
    pumpswap_persist_wait_seconds: list[float] = []
    pumpswap_radar_wait_seconds: list[float] = []
    pump_microbatch_sizes: list[int] = []
    enrichment_admitted = 0
    flow30_total = 0
    wallets_total = 0
    risk_missing = 0
    reference_asset_episodes = 0
    role_filtered_trades = 0
    unresolved_pumpswap_trades = 0

    def handle_radar_result(source: str, result) -> None:
        nonlocal enrichment_admitted, flow30_total, wallets_total, risk_missing
        nonlocal reference_asset_episodes
        radar_processed[source] += 1
        affected_tokens.update(result.affected_tokens)
        for hit in result.hits:
            hits_by_source[source] += 1
            episode = hit.episode
            if episode.token_mint in REFERENCE_ASSET_MINTS_V1:
                reference_asset_episodes += 1
            if episode.episode_key in episodes_seen:
                continue
            episodes_seen.add(episode.episode_key)
            episodes_by_source[source] += 1
            admitted = admit_opportunity_episode(
                acquisition_run_key=run_key,
                episode_key=episode.episode_key,
                admitted_at=episode.first_trigger_observed_at,
            )
            if not admitted:
                continue
            enrichment_admitted += 1
            bundle = build_episode_enrichment_bundle(
                episode=episode,
                as_of=episode.first_trigger_observed_at,
            )
            fast30 = next(item for item in bundle.core.flow_windows if item.window_seconds == 30)
            flow30_total += fast30.event_count
            wallets_total += bundle.wallet_intelligence.participant_wallet_count
            if bundle.risk.status != "available":
                risk_missing += 1
            print(
                f"[episode+bundle] id={_short_episode(episode.episode_key)} source={source} "
                f"token={episode.token_mint[:10]}… kind={episode.first_trigger_kind} "
                f"dir={episode.first_trigger_direction} flow30={fast30.event_count} "
                f"wallets={bundle.wallet_intelligence.participant_wallet_count} "
                f"execution_quotes={bundle.core.execution.quote_count} risk={bundle.risk.status}"
            )

    async def producer(source: str) -> None:
        queue = pump_queue if source == "pump" else pumpswap_queue
        stream = (
            iter_pump_log_notifications(rpc_url=settings.rpc_url, commitment=commitment)
            if source == "pump"
            else iter_pumpswap_log_notifications(rpc_url=settings.rpc_url, commitment=commitment)
        )
        iterator = stream.__aiter__()
        next_sequence = 0
        try:
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    notification = await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
                except (asyncio.TimeoutError, StopAsyncIteration):
                    break
                received[source] += 1
                item = QueuedNotification(next_sequence, notification, time.monotonic())
                try:
                    queue.put_nowait(item)
                except asyncio.QueueFull:
                    dropped[source] += 1
                    continue
                enqueued[source] += 1
                next_sequence += 1
                queue_high_water[source] = max(queue_high_water[source], queue.qsize())
        finally:
            await stream.aclose()

    async def pump_persist_worker() -> None:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                item = await asyncio.wait_for(pump_queue.get(), timeout=min(0.5, remaining))
            except asyncio.TimeoutError:
                continue
            try:
                pump_persist_wait_seconds.append(time.monotonic() - item.enqueued_monotonic)
                persist_result = await asyncio.to_thread(
                    persist_pump_notification_batch,
                    item.notification,
                    acquisition_run_key=run_key,
                )
                persistence_completed["pump"] += 1
                persisted_trades["pump"] += persist_result.newly_persisted_trades
                await pump_completed.put(
                    CompletedPumpNotification(
                        item.sequence, item.notification, persist_result, item.enqueued_monotonic
                    )
                )
            except Exception:
                worker_errors["pump_persist"] += 1
                raise
            finally:
                pump_queue.task_done()

    async def pump_microbatch_persist_worker() -> None:
        max_wait_seconds = pump_microbatch_max_wait_ms / 1000.0
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                first = await asyncio.wait_for(pump_queue.get(), timeout=min(0.5, remaining))
            except asyncio.TimeoutError:
                continue

            batch = [first]
            collect_started = time.monotonic()
            try:
                while len(batch) < pump_microbatch_size and time.monotonic() < deadline:
                    try:
                        batch.append(pump_queue.get_nowait())
                        continue
                    except asyncio.QueueEmpty:
                        pass

                    wait_left = max_wait_seconds - (time.monotonic() - collect_started)
                    deadline_left = deadline - time.monotonic()
                    timeout = min(wait_left, deadline_left)
                    if timeout <= 0:
                        break
                    try:
                        batch.append(await asyncio.wait_for(pump_queue.get(), timeout=timeout))
                    except asyncio.TimeoutError:
                        break

                dispatch_at = time.monotonic()
                for item in batch:
                    pump_persist_wait_seconds.append(dispatch_at - item.enqueued_monotonic)

                persist_results = await asyncio.to_thread(
                    persist_pump_notifications_microbatch,
                    tuple(item.notification for item in batch),
                    acquisition_run_key=run_key,
                )
                if len(persist_results) != len(batch):
                    raise RuntimeError("Pump microbatch result count does not match input count")

                pump_microbatch_sizes.append(len(batch))
                for item, persist_result in zip(batch, persist_results):
                    persistence_completed["pump"] += 1
                    persisted_trades["pump"] += persist_result.newly_persisted_trades
                    await pump_completed.put(
                        CompletedPumpNotification(
                            item.sequence,
                            item.notification,
                            persist_result,
                            item.enqueued_monotonic,
                        )
                    )
            except Exception:
                worker_errors["pump_microbatch_persist"] += 1
                raise
            finally:
                for _ in batch:
                    pump_queue.task_done()

    async def pump_radar_coordinator() -> None:
        next_sequence = 0
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                completed = await asyncio.wait_for(pump_completed.get(), timeout=min(0.5, remaining))
            except asyncio.TimeoutError:
                continue
            pending_pump[completed.sequence] = completed
            pump_completed.task_done()
            while next_sequence in pending_pump and time.monotonic() < deadline:
                item = pending_pump.pop(next_sequence)
                pump_radar_wait_seconds.append(time.monotonic() - item.enqueued_monotonic)
                try:
                    result = evaluate_persisted_pump_notification_for_radar_v4(
                        item.notification,
                        acquisition_run_key=run_key,
                        persist_result=item.persist_result,
                    )
                    handle_radar_result("pump", result)
                except Exception:
                    worker_errors["pump_radar"] += 1
                    raise
                next_sequence += 1

    async def pumpswap_persist_worker() -> None:
        nonlocal role_filtered_trades, unresolved_pumpswap_trades
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                item = await asyncio.wait_for(pumpswap_queue.get(), timeout=min(0.5, remaining))
            except asyncio.TimeoutError:
                continue
            try:
                pumpswap_persist_wait_seconds.append(time.monotonic() - item.enqueued_monotonic)
                persist_result = await persist_pumpswap_notification_normalized(
                    item.notification,
                    acquisition_run_key=run_key,
                    resolver=resolver,
                )
                persistence_completed["pumpswap"] += 1
                persisted_trades["pumpswap"] += persist_result.newly_persisted_trades
                role_filtered_trades += persist_result.role_filtered_trades
                unresolved_pumpswap_trades += persist_result.unresolved_trades
                await pumpswap_completed.put(
                    CompletedPumpSwapNotification(
                        item.sequence, item.notification, persist_result, item.enqueued_monotonic
                    )
                )
            except Exception:
                worker_errors["pumpswap_persist"] += 1
                raise
            finally:
                pumpswap_queue.task_done()

    async def pumpswap_radar_coordinator() -> None:
        next_sequence = 0
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                completed = await asyncio.wait_for(pumpswap_completed.get(), timeout=min(0.5, remaining))
            except asyncio.TimeoutError:
                continue
            pending_pumpswap[completed.sequence] = completed
            pumpswap_completed.task_done()
            while next_sequence in pending_pumpswap and time.monotonic() < deadline:
                item = pending_pumpswap.pop(next_sequence)
                pumpswap_radar_wait_seconds.append(time.monotonic() - item.enqueued_monotonic)
                try:
                    result = evaluate_persisted_pumpswap_notification_for_radar_v3(
                        item.notification,
                        acquisition_run_key=run_key,
                        persist_result=item.persist_result,
                    )
                    handle_radar_result("pumpswap", result)
                except Exception:
                    worker_errors["pumpswap_radar"] += 1
                    raise
                next_sequence += 1

    tasks = [
        asyncio.create_task(producer("pump"), name="producer-pump"),
        asyncio.create_task(producer("pumpswap"), name="producer-pumpswap"),
        asyncio.create_task(pump_radar_coordinator(), name="radar-pump"),
        asyncio.create_task(pumpswap_radar_coordinator(), name="radar-pumpswap"),
    ]
    if pump_microbatch_size > 1:
        tasks.append(
            asyncio.create_task(pump_microbatch_persist_worker(), name="persist-pump-microbatch")
        )
    else:
        tasks.extend(
            asyncio.create_task(pump_persist_worker(), name=f"persist-pump-{index}")
            for index in range(pump_workers)
        )
    tasks.extend(
        asyncio.create_task(pumpswap_persist_worker(), name=f"persist-pumpswap-{index}")
        for index in range(pumpswap_workers)
    )

    try:
        while time.monotonic() < deadline:
            for task in tasks:
                if task.done() and not task.cancelled():
                    exception = task.exception()
                    if exception is not None:
                        raise exception
            await asyncio.sleep(0.1)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    elapsed = time.monotonic() - started
    resolver_operational_skips = resolver.hydration_budget_skips + resolver.negative_cache_skips
    resolver_rpc_failures = max(0, resolver.hydration_failures - resolver_operational_skips)

    pump_ingress_backlog = pump_queue.qsize()
    pump_reorder_backlog = len(pending_pump) + pump_completed.qsize()
    pump_inflight = max(0, enqueued["pump"] - persistence_completed["pump"] - pump_ingress_backlog)
    pumpswap_ingress_backlog = pumpswap_queue.qsize()
    pumpswap_reorder_backlog = len(pending_pumpswap) + pumpswap_completed.qsize()
    pumpswap_inflight = max(
        0, enqueued["pumpswap"] - persistence_completed["pumpswap"] - pumpswap_ingress_backlog
    )
    total_received = sum(received.values())
    total_radar_processed = sum(radar_processed.values())
    coverage_pct = 100.0 * total_radar_processed / total_received if total_received else 0.0

    print("\nSUMMARY")
    print(
        f"elapsed={elapsed:.1f}s deadline_overrun={max(0.0, elapsed-duration_seconds):.1f}s "
        f"received={dict(received)} enqueued={dict(enqueued)} dropped={dict(dropped)}"
    )
    print(
        f"persistence_completed={dict(persistence_completed)} radar_processed={dict(radar_processed)} "
        f"radar_coverage_pct={coverage_pct:.1f}% worker_errors={dict(worker_errors)}"
    )
    print(
        "backlog_at_deadline={"
        f"'pump_ingress': {pump_ingress_backlog}, 'pump_inflight': {pump_inflight}, "
        f"'pump_reorder': {pump_reorder_backlog}, 'pumpswap_ingress': {pumpswap_ingress_backlog}, "
        f"'pumpswap_inflight': {pumpswap_inflight}, 'pumpswap_reorder': {pumpswap_reorder_backlog}"
        "} "
        f"queue_high_water={dict(queue_high_water)} queue_size={queue_size}"
    )
    print(
        f"persisted_trades={dict(persisted_trades)} role_filtered_pumpswap_trades={role_filtered_trades} "
        f"unresolved_pumpswap_trades={unresolved_pumpswap_trades} affected_tokens={len(affected_tokens)}"
    )
    print(
        f"raw_radar_hits={dict(hits_by_source)} unique_episodes={len(episodes_seen)} "
        f"opened_by_source={dict(episodes_by_source)} enrichment_admitted={enrichment_admitted} "
        f"reference_asset_episodes={reference_asset_episodes}"
    )
    print(
        f"bundle_wallets_total={wallets_total} bundle_flow30_total={flow30_total} risk_missing={risk_missing}"
    )
    print(f"pump_persist_queue_wait_ms {_latency_summary_ms(pump_persist_wait_seconds)}")
    print(f"pump_radar_end_to_end_wait_ms {_latency_summary_ms(pump_radar_wait_seconds)}")
    if pump_microbatch_size > 1:
        avg_batch = sum(pump_microbatch_sizes) / len(pump_microbatch_sizes) if pump_microbatch_sizes else 0.0
        max_batch = max(pump_microbatch_sizes) if pump_microbatch_sizes else 0
        print(
            f"pump_microbatch batches={len(pump_microbatch_sizes)} avg_size={avg_batch:.2f} "
            f"max_size={max_batch} configured_size={pump_microbatch_size} "
            f"max_wait_ms={pump_microbatch_max_wait_ms}"
        )
    print(f"pumpswap_persist_queue_wait_ms {_latency_summary_ms(pumpswap_persist_wait_seconds)}")
    print(f"pumpswap_radar_end_to_end_wait_ms {_latency_summary_ms(pumpswap_radar_wait_seconds)}")
    print(
        f"pumpswap_historical_pool_hits={resolver.historical_store_hits} "
        f"pumpswap_run_store_hits={resolver.store_hits} cache_hits={resolver.cache_hits} "
        f"singleflight_waits={resolver.singleflight_waits} network_hydrations={resolver.network_hydration_calls} "
        f"hydration_successes={resolver.hydration_successes} rpc_failures={resolver_rpc_failures} "
        f"budget_skips={resolver.hydration_budget_skips} negative_cache_skips={resolver.negative_cache_skips}"
    )
    if pump_microbatch_size > 1:
        print(
            "Pump persistence uses one ordered SQLite microbatch writer; PumpSwap keeps bounded "
            "concurrent resolution/persistence. Radar ordering and detector semantics are unchanged. "
            "Execution/risk providers are not called."
        )
    else:
        print(
            "v4 preserves websocket ingress ordering for both Pump and PumpSwap radar while allowing "
            "bounded concurrent persistence. Execution/risk providers are not called."
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", choices=("processed", "confirmed", "finalized"), default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1000)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-workers", type=int, default=4)
    parser.add_argument("--pumpswap-workers", type=int, default=8)
    parser.add_argument("--max-concurrent-resolutions", type=int, default=6)
    parser.add_argument("--queue-size", type=int, default=5000)
    args = parser.parse_args()
    if not 1 <= args.duration_seconds <= MAX_SMOKE_SECONDS:
        parser.error(f"duration-seconds must be between 1 and {MAX_SMOKE_SECONDS}")
    for name in ("max_hydrations", "rpc_timeout_seconds", "pump_workers", "pumpswap_workers", "max_concurrent_resolutions", "queue_size"):
        if getattr(args, name) <= 0:
            parser.error(f"{name.replace('_', '-')} must be positive")
    return args


def main() -> None:
    args = _parse_args()
    print("Crypto Copy Trader — Unified Market Throughput Smoke v4")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"pump_workers={args.pump_workers} pumpswap_workers={args.pumpswap_workers} "
        f"concurrent_resolutions={args.max_concurrent_resolutions} max_hydrations={args.max_hydrations} "
        f"queue_size={args.queue_size}"
    )
    asyncio.run(
        run_smoke(
            run_key=args.run_key,
            duration_seconds=args.duration_seconds,
            commitment=args.commitment,
            max_hydrations=args.max_hydrations,
            rpc_timeout_seconds=args.rpc_timeout_seconds,
            pump_workers=args.pump_workers,
            pumpswap_workers=args.pumpswap_workers,
            max_concurrent_resolutions=args.max_concurrent_resolutions,
            queue_size=args.queue_size,
        )
    )


if __name__ == "__main__":
    main()
