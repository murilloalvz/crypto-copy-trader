import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
import time

from src.config import settings
from src.opportunity_enrichment_store import admit_opportunity_episode
from src.opportunity_episode_enrichment import build_episode_enrichment_bundle
from src.pump_bonding_stream import iter_pump_log_notifications
from src.pump_microbatch_persistence import persist_pump_notifications_microbatch
from src.pump_radar_bridge_v4 import evaluate_persisted_pump_notification_for_radar_v4
from src.pumpswap_asset_role import REFERENCE_ASSET_MINTS_V1
from src.pumpswap_normalized_persistence import persist_pumpswap_notification_normalized
from src.pumpswap_radar_bridge_v5 import (
    PreparedPumpSwapRadarV5,
    finalize_prepared_pumpswap_radar_v5,
    prepare_persisted_pumpswap_notification_for_radar_v5,
)
from src.pumpswap_ready_scheduler import AssetReservation, ReadyAssetScheduler
from src.pumpswap_stream import iter_pumpswap_log_notifications
from unified_market_latency_smoke_v5 import _print_replay_telemetry
from unified_market_latency_smoke_v8 import BoundedConcurrentResolver, _short_episode
from unified_market_latency_smoke_v10 import (
    TimedPumpSwapCompletion,
    _concentration_asset_count,
    _format_hot_assets,
)
from unified_market_throughput_smoke_v4 import (
    MAX_SMOKE_SECONDS,
    CompletedPumpNotification,
    CompletedPumpSwapNotification,
    QueuedNotification,
    _latency_summary_ms,
)


@dataclass(frozen=True)
class PreparedTimedPumpSwapWork:
    timed: TimedPumpSwapCompletion
    prepared: PreparedPumpSwapRadarV5
    prepare_started_monotonic: float
    prepare_completed_monotonic: float

    @property
    def sequence(self) -> int:
        return self.timed.completed.sequence


async def run_smoke_v11(
    *,
    run_key: str,
    duration_seconds: int,
    commitment: str,
    max_hydrations: int,
    rpc_timeout_seconds: int,
    pump_batch_size: int,
    pump_batch_max_wait_ms: int,
    pumpswap_workers: int,
    pumpswap_radar_workers: int,
    max_concurrent_resolutions: int,
    queue_size: int,
) -> None:
    """Run v11 with parallel causal preparation and FIFO-only episode finalization."""

    started = time.monotonic()
    deadline = started + duration_seconds

    pump_queue: asyncio.Queue[QueuedNotification] = asyncio.Queue(maxsize=queue_size)
    pump_completed: asyncio.Queue[CompletedPumpNotification] = asyncio.Queue()

    pumpswap_queue: asyncio.Queue[QueuedNotification] = asyncio.Queue(maxsize=queue_size)
    pumpswap_order_completed: asyncio.Queue[TimedPumpSwapCompletion] = asyncio.Queue()
    pumpswap_prepare_queue: asyncio.Queue[TimedPumpSwapCompletion] = asyncio.Queue()
    scheduler: ReadyAssetScheduler[PreparedTimedPumpSwapWork] = ReadyAssetScheduler()

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
    duplicate_trades: Counter[str] = Counter()
    hits_by_source: Counter[str] = Counter()
    episodes_by_source: Counter[str] = Counter()
    queue_high_water: Counter[str] = Counter()
    worker_errors: Counter[str] = Counter()

    affected_tokens: set[str] = set()
    episodes_seen: set[str] = set()
    pending_pump: dict[int, CompletedPumpNotification] = {}
    pending_pumpswap_order: dict[int, TimedPumpSwapCompletion] = {}
    prepared_by_sequence: dict[int, PreparedTimedPumpSwapWork] = {}
    reservations_by_sequence: dict[int, AssetReservation] = {}
    scheduler_submit_times: dict[int, float] = {}

    pump_persist_wait_seconds: list[float] = []
    pump_radar_wait_seconds: list[float] = []
    pump_microbatch_sizes: list[int] = []

    pumpswap_persist_wait_seconds: list[float] = []
    pumpswap_persist_service_seconds: list[float] = []
    pumpswap_persist_to_reservation_seconds: list[float] = []
    pumpswap_prepare_queue_wait_seconds: list[float] = []
    pumpswap_prepare_service_seconds: list[float] = []
    pumpswap_prepare_end_to_end_seconds: list[float] = []
    pumpswap_prepared_to_submit_seconds: list[float] = []
    pumpswap_reservation_to_submit_seconds: list[float] = []
    pumpswap_scheduler_dispatch_wait_seconds: list[float] = []
    pumpswap_dependency_wait_seconds: list[float] = []
    pumpswap_ready_queue_wait_seconds: list[float] = []
    pumpswap_finalize_wait_seconds: list[float] = []
    pumpswap_finalize_service_seconds: list[float] = []
    pumpswap_post_finalize_seconds: list[float] = []
    pumpswap_compute_service_seconds: list[float] = []
    pumpswap_pipeline_end_to_end_seconds: list[float] = []

    pumpswap_transaction_read_seconds: list[float] = []
    pumpswap_history_read_seconds: list[float] = []
    pumpswap_db_read_seconds: list[float] = []
    pumpswap_detect_seconds: list[float] = []
    pumpswap_episode_assign_seconds: list[float] = []

    pumpswap_asset_reservations = 0
    pumpswap_multi_asset_notifications = 0
    pumpswap_max_assets_per_notification = 0
    no_new_evidence_skips = 0
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
            fast30 = next(
                item for item in bundle.core.flow_windows if item.window_seconds == 30
            )
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

    def has_new_evidence(timed: TimedPumpSwapCompletion) -> bool:
        result = timed.completed.persist_result
        return (
            result.newly_persisted_trades > 0
            or result.newly_persisted_lifecycle > 0
        )

    def maybe_submit(sequence: int) -> None:
        prepared_work = prepared_by_sequence.get(sequence)
        reservation = reservations_by_sequence.get(sequence)
        if prepared_work is None or reservation is None:
            return
        submit_time = time.monotonic()
        pumpswap_prepared_to_submit_seconds.append(
            max(0.0, submit_time - prepared_work.prepare_completed_monotonic)
        )
        pumpswap_reservation_to_submit_seconds.append(
            max(0.0, submit_time - reservation.created_monotonic)
        )
        scheduler_submit_times[sequence] = submit_time
        scheduler.submit(prepared_work, reservation)
        del prepared_by_sequence[sequence]
        del reservations_by_sequence[sequence]

    async def producer(source: str) -> None:
        queue = pump_queue if source == "pump" else pumpswap_queue
        stream = (
            iter_pump_log_notifications(
                rpc_url=settings.rpc_url,
                commitment=commitment,
            )
            if source == "pump"
            else iter_pumpswap_log_notifications(
                rpc_url=settings.rpc_url,
                commitment=commitment,
            )
        )
        iterator = stream.__aiter__()
        next_sequence = 0
        try:
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    notification = await asyncio.wait_for(
                        iterator.__anext__(),
                        timeout=remaining,
                    )
                except (asyncio.TimeoutError, StopAsyncIteration):
                    break
                received[source] += 1
                item = QueuedNotification(
                    next_sequence,
                    notification,
                    time.monotonic(),
                )
                try:
                    queue.put_nowait(item)
                except asyncio.QueueFull:
                    dropped[source] += 1
                    continue
                enqueued[source] += 1
                next_sequence += 1
                queue_high_water[source] = max(
                    queue_high_water[source],
                    queue.qsize(),
                )
        finally:
            await stream.aclose()

    async def pump_microbatch_worker() -> None:
        max_wait_seconds = pump_batch_max_wait_ms / 1000.0
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                first = await asyncio.wait_for(
                    pump_queue.get(),
                    timeout=min(0.5, remaining),
                )
            except asyncio.TimeoutError:
                continue
            batch = [first]
            collect_started = time.monotonic()
            try:
                while len(batch) < pump_batch_size and time.monotonic() < deadline:
                    try:
                        batch.append(pump_queue.get_nowait())
                        continue
                    except asyncio.QueueEmpty:
                        pass
                    timeout = min(
                        max_wait_seconds - (time.monotonic() - collect_started),
                        deadline - time.monotonic(),
                    )
                    if timeout <= 0:
                        break
                    try:
                        batch.append(
                            await asyncio.wait_for(
                                pump_queue.get(),
                                timeout=timeout,
                            )
                        )
                    except asyncio.TimeoutError:
                        break

                dispatched = time.monotonic()
                for item in batch:
                    pump_persist_wait_seconds.append(
                        dispatched - item.enqueued_monotonic
                    )
                results = await asyncio.to_thread(
                    persist_pump_notifications_microbatch,
                    tuple(item.notification for item in batch),
                    acquisition_run_key=run_key,
                )
                if len(results) != len(batch):
                    raise RuntimeError(
                        "Pump microbatch result count does not match input count"
                    )
                pump_microbatch_sizes.append(len(batch))
                for item, result in zip(batch, results):
                    persistence_completed["pump"] += 1
                    persisted_trades["pump"] += result.newly_persisted_trades
                    await pump_completed.put(
                        CompletedPumpNotification(
                            item.sequence,
                            item.notification,
                            result,
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
                completed = await asyncio.wait_for(
                    pump_completed.get(),
                    timeout=min(0.5, remaining),
                )
            except asyncio.TimeoutError:
                continue
            pending_pump[completed.sequence] = completed
            pump_completed.task_done()
            while next_sequence in pending_pump and time.monotonic() < deadline:
                item = pending_pump.pop(next_sequence)
                pump_radar_wait_seconds.append(
                    time.monotonic() - item.enqueued_monotonic
                )
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
                item = await asyncio.wait_for(
                    pumpswap_queue.get(),
                    timeout=min(0.5, remaining),
                )
            except asyncio.TimeoutError:
                continue

            persistence_started_at = time.monotonic()
            try:
                pumpswap_persist_wait_seconds.append(
                    persistence_started_at - item.enqueued_monotonic
                )
                result = await persist_pumpswap_notification_normalized(
                    item.notification,
                    acquisition_run_key=run_key,
                    resolver=resolver,
                )
                persistence_completed_at = time.monotonic()
                pumpswap_persist_service_seconds.append(
                    persistence_completed_at - persistence_started_at
                )
                persistence_completed["pumpswap"] += 1
                persisted_trades["pumpswap"] += result.newly_persisted_trades
                duplicate_trades["pumpswap"] += result.duplicate_or_replayed_trades
                role_filtered_trades += result.role_filtered_trades
                unresolved_pumpswap_trades += result.unresolved_trades

                timed = TimedPumpSwapCompletion(
                    completed=CompletedPumpSwapNotification(
                        item.sequence,
                        item.notification,
                        result,
                        item.enqueued_monotonic,
                    ),
                    persistence_started_monotonic=persistence_started_at,
                    persistence_completed_monotonic=persistence_completed_at,
                )
                await pumpswap_order_completed.put(timed)
                if has_new_evidence(timed):
                    await pumpswap_prepare_queue.put(timed)
            except Exception:
                worker_errors["pumpswap_persist"] += 1
                raise
            finally:
                pumpswap_queue.task_done()

    async def pumpswap_order_dispatcher() -> None:
        nonlocal pumpswap_asset_reservations, pumpswap_multi_asset_notifications
        nonlocal pumpswap_max_assets_per_notification, no_new_evidence_skips
        next_sequence = 0
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                timed = await asyncio.wait_for(
                    pumpswap_order_completed.get(),
                    timeout=min(0.5, remaining),
                )
            except asyncio.TimeoutError:
                continue

            pending_pumpswap_order[timed.completed.sequence] = timed
            pumpswap_order_completed.task_done()

            while (
                next_sequence in pending_pumpswap_order
                and time.monotonic() < deadline
            ):
                timed = pending_pumpswap_order.pop(next_sequence)
                item = timed.completed
                if not has_new_evidence(timed):
                    no_new_evidence_skips += 1
                    now = time.monotonic()
                    radar_processed["pumpswap"] += 1
                    pumpswap_finalize_wait_seconds.append(
                        now - item.enqueued_monotonic
                    )
                    pumpswap_pipeline_end_to_end_seconds.append(
                        now - item.enqueued_monotonic
                    )
                    next_sequence += 1
                    continue

                reservation = scheduler.reserve(
                    item.persist_result.affected_tokens
                )
                pumpswap_persist_to_reservation_seconds.append(
                    max(
                        0.0,
                        reservation.created_monotonic
                        - timed.persistence_completed_monotonic,
                    )
                )
                pumpswap_asset_reservations += 1
                pumpswap_max_assets_per_notification = max(
                    pumpswap_max_assets_per_notification,
                    len(reservation.assets),
                )
                if len(reservation.assets) > 1:
                    pumpswap_multi_asset_notifications += 1

                reservations_by_sequence[item.sequence] = reservation
                maybe_submit(item.sequence)
                next_sequence += 1

    async def pumpswap_prepare_worker() -> None:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                timed = await asyncio.wait_for(
                    pumpswap_prepare_queue.get(),
                    timeout=min(0.5, remaining),
                )
            except asyncio.TimeoutError:
                continue

            prepare_started = time.monotonic()
            try:
                pumpswap_prepare_queue_wait_seconds.append(
                    max(
                        0.0,
                        prepare_started - timed.persistence_completed_monotonic,
                    )
                )
                prepared = await asyncio.to_thread(
                    prepare_persisted_pumpswap_notification_for_radar_v5,
                    timed.completed.notification,
                    acquisition_run_key=run_key,
                    persist_result=timed.completed.persist_result,
                )
                prepare_completed = time.monotonic()
                prepare_service = prepare_completed - prepare_started
                pumpswap_prepare_service_seconds.append(prepare_service)
                pumpswap_prepare_end_to_end_seconds.append(
                    prepare_completed - timed.completed.enqueued_monotonic
                )

                telemetry = prepared
                pumpswap_transaction_read_seconds.append(
                    telemetry.transaction_view_read_seconds
                )
                pumpswap_history_read_seconds.append(
                    telemetry.history_read_seconds
                )
                pumpswap_db_read_seconds.append(telemetry.db_read_seconds)
                pumpswap_detect_seconds.append(telemetry.detect_seconds)

                work = PreparedTimedPumpSwapWork(
                    timed=timed,
                    prepared=prepared,
                    prepare_started_monotonic=prepare_started,
                    prepare_completed_monotonic=prepare_completed,
                )
                prepared_by_sequence[work.sequence] = work
                maybe_submit(work.sequence)
            except Exception:
                worker_errors["pumpswap_prepare"] += 1
                raise
            finally:
                pumpswap_prepare_queue.task_done()

    async def pumpswap_finalize_worker() -> None:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                work = await asyncio.wait_for(
                    scheduler.get_ready(),
                    timeout=min(0.5, remaining),
                )
            except asyncio.TimeoutError:
                continue

            started_finalize = time.monotonic()
            try:
                prepared_work = work.payload
                item = prepared_work.timed.completed

                submitted_at = scheduler_submit_times.pop(
                    prepared_work.sequence,
                    work.reservation.created_monotonic,
                )
                pumpswap_scheduler_dispatch_wait_seconds.append(
                    max(
                        0.0,
                        work.waiter_started_monotonic - submitted_at,
                    )
                )
                pumpswap_dependency_wait_seconds.append(
                    max(
                        0.0,
                        work.dependency_ready_monotonic
                        - work.waiter_started_monotonic,
                    )
                )
                pumpswap_ready_queue_wait_seconds.append(
                    max(
                        0.0,
                        started_finalize - work.ready_queue_entered_monotonic,
                    )
                )
                pumpswap_finalize_wait_seconds.append(
                    started_finalize - item.enqueued_monotonic
                )

                result = finalize_prepared_pumpswap_radar_v5(
                    prepared_work.prepared,
                    acquisition_run_key=run_key,
                )
                finalized = time.monotonic()
                pumpswap_finalize_service_seconds.append(
                    finalized - started_finalize
                )
                pumpswap_episode_assign_seconds.append(
                    result.telemetry.episode_assign_seconds
                )

                # Only trigger/episode assignment needs per-asset FIFO.
                await scheduler.complete(work.reservation)

                handle_radar_result("pumpswap", result)
                finished = time.monotonic()
                pumpswap_post_finalize_seconds.append(
                    finished - finalized
                )
                pumpswap_compute_service_seconds.append(
                    (prepared_work.prepare_completed_monotonic
                     - prepared_work.prepare_started_monotonic)
                    + (finished - started_finalize)
                )
                pumpswap_pipeline_end_to_end_seconds.append(
                    finished - item.enqueued_monotonic
                )
            except Exception:
                worker_errors["pumpswap_finalize"] += 1
                raise
            finally:
                scheduler.ready_task_done()

    tasks = [
        asyncio.create_task(
            producer("pump"),
            name="producer-pump",
        ),
        asyncio.create_task(
            producer("pumpswap"),
            name="producer-pumpswap",
        ),
        asyncio.create_task(
            pump_microbatch_worker(),
            name="persist-pump-microbatch",
        ),
        asyncio.create_task(
            pump_radar_coordinator(),
            name="radar-pump",
        ),
        asyncio.create_task(
            pumpswap_order_dispatcher(),
            name="pumpswap-order-dispatcher",
        ),
        asyncio.create_task(
            pumpswap_finalize_worker(),
            name="pumpswap-fifo-finalize",
        ),
    ]
    tasks.extend(
        asyncio.create_task(
            pumpswap_persist_worker(),
            name=f"persist-pumpswap-{index}",
        )
        for index in range(pumpswap_workers)
    )
    tasks.extend(
        asyncio.create_task(
            pumpswap_prepare_worker(),
            name=f"prepare-pumpswap-{index}",
        )
        for index in range(pumpswap_radar_workers)
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
        await scheduler.cancel_waiters()

    elapsed = time.monotonic() - started
    resolver_operational_skips = (
        resolver.hydration_budget_skips + resolver.negative_cache_skips
    )
    resolver_rpc_failures = max(
        0,
        resolver.hydration_failures - resolver_operational_skips,
    )

    pump_ingress = pump_queue.qsize()
    pump_reorder = len(pending_pump) + pump_completed.qsize()
    pump_inflight = max(
        0,
        enqueued["pump"]
        - persistence_completed["pump"]
        - pump_ingress,
    )

    ps_ingress = pumpswap_queue.qsize()
    ps_inflight = max(
        0,
        enqueued["pumpswap"]
        - persistence_completed["pumpswap"]
        - ps_ingress,
    )
    ps_total_radar_backlog = max(
        0,
        persistence_completed["pumpswap"]
        - radar_processed["pumpswap"],
    )
    ps_order_backlog = (
        len(pending_pumpswap_order) + pumpswap_order_completed.qsize()
    )
    ps_prepare_backlog = pumpswap_prepare_queue.qsize()
    ps_prepared_waiting_reservation = len(prepared_by_sequence)
    ps_reservation_waiting_prepare = len(reservations_by_sequence)

    total_received = sum(received.values())
    total_processed = sum(radar_processed.values())
    coverage = (
        100.0 * total_processed / total_received
        if total_received
        else 0.0
    )

    scheduler_snapshot = scheduler.pre_cancel_snapshot()
    asset_telemetry = scheduler_snapshot.asset_telemetry
    causal_50 = _concentration_asset_count(asset_telemetry, 0.50)
    causal_90 = _concentration_asset_count(asset_telemetry, 0.90)
    max_waiting_per_asset = max(
        (item.max_waiting_jobs for item in asset_telemetry),
        default=0,
    )

    print("\nSUMMARY")
    print(
        f"elapsed={elapsed:.1f}s "
        f"deadline_overrun={max(0.0, elapsed-duration_seconds):.1f}s "
        f"received={dict(received)} enqueued={dict(enqueued)} "
        f"dropped={dict(dropped)}"
    )
    print(
        f"persistence_completed={dict(persistence_completed)} "
        f"radar_processed={dict(radar_processed)} "
        f"radar_coverage_pct={coverage:.1f}% "
        f"worker_errors={dict(worker_errors)}"
    )
    print(
        "backlog_at_deadline={"
        f"'pump_ingress': {pump_ingress}, "
        f"'pump_inflight': {pump_inflight}, "
        f"'pump_reorder': {pump_reorder}, "
        f"'pumpswap_ingress': {ps_ingress}, "
        f"'pumpswap_inflight': {ps_inflight}, "
        f"'pumpswap_total_radar': {ps_total_radar_backlog}, "
        f"'pumpswap_order_reorder': {ps_order_backlog}, "
        f"'pumpswap_prepare_queue': {ps_prepare_backlog}, "
        f"'pumpswap_prepared_waiting_reservation': "
        f"{ps_prepared_waiting_reservation}, "
        f"'pumpswap_reservation_waiting_prepare': "
        f"{ps_reservation_waiting_prepare}, "
        f"'pumpswap_ready': {scheduler_snapshot.ready_backlog}, "
        f"'pumpswap_waiting': {scheduler_snapshot.waiting_backlog}"
        "} "
        f"queue_high_water={dict(queue_high_water)} "
        f"queue_size={queue_size}"
    )
    print(
        f"persisted_trades={dict(persisted_trades)} "
        f"duplicate_or_replayed_trades={dict(duplicate_trades)} "
        f"role_filtered_pumpswap_trades={role_filtered_trades} "
        f"unresolved_pumpswap_trades={unresolved_pumpswap_trades} "
        f"affected_tokens={len(affected_tokens)}"
    )
    print(
        f"raw_radar_hits={dict(hits_by_source)} "
        f"unique_episodes={len(episodes_seen)} "
        f"opened_by_source={dict(episodes_by_source)} "
        f"enrichment_admitted={enrichment_admitted} "
        f"reference_asset_episodes={reference_asset_episodes}"
    )
    print(
        f"bundle_wallets_total={wallets_total} "
        f"bundle_flow30_total={flow30_total} "
        f"risk_missing={risk_missing}"
    )

    print(
        f"pump_persist_queue_wait_ms "
        f"{_latency_summary_ms(pump_persist_wait_seconds)}"
    )
    print(
        f"pump_radar_end_to_end_wait_ms "
        f"{_latency_summary_ms(pump_radar_wait_seconds)}"
    )
    avg_batch = (
        sum(pump_microbatch_sizes) / len(pump_microbatch_sizes)
        if pump_microbatch_sizes
        else 0.0
    )
    max_batch = max(pump_microbatch_sizes) if pump_microbatch_sizes else 0
    print(
        f"pump_microbatch batches={len(pump_microbatch_sizes)} "
        f"avg_size={avg_batch:.2f} max_size={max_batch} "
        f"configured_size={pump_batch_size} "
        f"max_wait_ms={pump_batch_max_wait_ms}"
    )

    print(
        f"pumpswap_persist_queue_wait_ms "
        f"{_latency_summary_ms(pumpswap_persist_wait_seconds)}"
    )
    print(
        f"pumpswap_persistence_service_time_ms "
        f"{_latency_summary_ms(pumpswap_persist_service_seconds)}"
    )
    print(
        f"pumpswap_persist_to_reservation_wait_ms "
        f"{_latency_summary_ms(pumpswap_persist_to_reservation_seconds)}"
    )
    print(
        f"pumpswap_prepare_queue_wait_ms "
        f"{_latency_summary_ms(pumpswap_prepare_queue_wait_seconds)}"
    )
    print(
        f"pumpswap_prepare_service_time_ms "
        f"{_latency_summary_ms(pumpswap_prepare_service_seconds)}"
    )
    print(
        f"pumpswap_prepare_end_to_end_ms "
        f"{_latency_summary_ms(pumpswap_prepare_end_to_end_seconds)}"
    )
    print(
        f"pumpswap_prepared_to_submit_wait_ms "
        f"{_latency_summary_ms(pumpswap_prepared_to_submit_seconds)}"
    )
    print(
        f"pumpswap_reservation_to_submit_wait_ms "
        f"{_latency_summary_ms(pumpswap_reservation_to_submit_seconds)}"
    )
    print(
        f"pumpswap_scheduler_dispatch_wait_ms "
        f"{_latency_summary_ms(pumpswap_scheduler_dispatch_wait_seconds)}"
    )
    print(
        f"pumpswap_finalize_causal_dependency_wait_ms "
        f"{_latency_summary_ms(pumpswap_dependency_wait_seconds)}"
    )
    print(
        f"pumpswap_finalize_ready_queue_wait_ms "
        f"{_latency_summary_ms(pumpswap_ready_queue_wait_seconds)}"
    )
    print(
        f"pumpswap_finalize_start_end_to_end_wait_ms "
        f"{_latency_summary_ms(pumpswap_finalize_wait_seconds)}"
    )
    print(
        f"pumpswap_finalize_service_time_ms "
        f"{_latency_summary_ms(pumpswap_finalize_service_seconds)}"
    )
    print(
        f"pumpswap_post_finalize_time_ms "
        f"{_latency_summary_ms(pumpswap_post_finalize_seconds)}"
    )
    print(
        f"pumpswap_compute_service_time_ms "
        f"{_latency_summary_ms(pumpswap_compute_service_seconds)}"
    )
    print(
        f"pumpswap_pipeline_end_to_end_ms "
        f"{_latency_summary_ms(pumpswap_pipeline_end_to_end_seconds)}"
    )

    print(
        f"pumpswap_radar_transaction_view_read_ms "
        f"{_latency_summary_ms(pumpswap_transaction_read_seconds)}"
    )
    print(
        f"pumpswap_radar_history_read_ms "
        f"{_latency_summary_ms(pumpswap_history_read_seconds)}"
    )
    print(
        f"pumpswap_radar_db_read_total_ms "
        f"{_latency_summary_ms(pumpswap_db_read_seconds)}"
    )
    print(
        f"pumpswap_radar_detect_compute_ms "
        f"{_latency_summary_ms(pumpswap_detect_seconds)}"
    )
    print(
        f"pumpswap_radar_episode_assign_ms "
        f"{_latency_summary_ms(pumpswap_episode_assign_seconds)}"
    )

    print(
        f"pumpswap_split_radar prepare_workers={pumpswap_radar_workers} "
        f"finalize_workers=1 reservations={pumpswap_asset_reservations} "
        f"multi_asset_notifications={pumpswap_multi_asset_notifications} "
        f"max_assets_per_notification={pumpswap_max_assets_per_notification} "
        f"ready_backlog={scheduler_snapshot.ready_backlog} "
        f"waiting_backlog={scheduler_snapshot.waiting_backlog} "
        f"no_new_evidence_skips={no_new_evidence_skips}"
    )
    print(
        "pumpswap_finalize_causal_asset_concentration "
        f"assets_with_reservations="
        f"{sum(1 for item in asset_telemetry if item.reservations > 0)} "
        f"assets_with_causal_wait="
        f"{sum(1 for item in asset_telemetry if item.dependency_wait_total_seconds > 0)} "
        f"assets_for_50pct_wait={causal_50} "
        f"assets_for_90pct_wait={causal_90} "
        f"max_waiting_jobs_single_asset={max_waiting_per_asset}"
    )
    print(
        "pumpswap_hot_assets_by_reservations "
        + _format_hot_assets(
            asset_telemetry,
            key="reservations",
        )
    )
    print(
        "pumpswap_hot_assets_by_finalize_causal_wait "
        + _format_hot_assets(
            asset_telemetry,
            key="causal_wait",
        )
    )

    print(
        f"pumpswap_historical_pool_hits={resolver.historical_store_hits} "
        f"pumpswap_run_store_hits={resolver.store_hits} "
        f"cache_hits={resolver.cache_hits} "
        f"singleflight_waits={resolver.singleflight_waits} "
        f"network_hydrations={resolver.network_hydration_calls} "
        f"hydration_successes={resolver.hydration_successes} "
        f"rpc_failures={resolver_rpc_failures} "
        f"budget_skips={resolver.hydration_budget_skips} "
        f"negative_cache_skips={resolver.negative_cache_skips}"
    )
    print(
        "v11 overlaps PumpSwap transaction/history reads and detector compute across "
        "same-asset notifications, while per-asset FIFO protects only trigger/episode "
        "finalization. Detector thresholds, causal as_of clocks, trigger keys, replay "
        "semantics, pool resolution, persistence semantics and provider policy are unchanged. "
        "Preparation workers remain 8 under the frozen smoke config. Jupiter/risk/12h remain blocked."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v11 prepared-radar split"
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1500)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-batch-size", type=int, default=32)
    parser.add_argument("--pump-batch-max-wait-ms", type=int, default=25)
    parser.add_argument("--pumpswap-workers", type=int, default=24)
    parser.add_argument("--pumpswap-radar-workers", type=int, default=8)
    parser.add_argument("--max-concurrent-resolutions", type=int, default=18)
    parser.add_argument("--queue-size", type=int, default=5000)
    args = parser.parse_args()

    if not 1 <= args.duration_seconds <= MAX_SMOKE_SECONDS:
        parser.error(
            f"duration-seconds must be between 1 and {MAX_SMOKE_SECONDS}"
        )
    if args.pump_batch_size <= 1:
        parser.error("pump-batch-size must be greater than 1")
    if args.pump_batch_max_wait_ms < 0:
        parser.error("pump-batch-max-wait-ms cannot be negative")
    for name in (
        "max_hydrations",
        "rpc_timeout_seconds",
        "pumpswap_workers",
        "pumpswap_radar_workers",
        "max_concurrent_resolutions",
        "queue_size",
    ):
        if getattr(args, name) <= 0:
            parser.error(
                f"{name.replace('_', '-')} must be positive"
            )

    print(
        "Crypto Copy Trader — Unified Market Latency Smoke v11 Prepared Radar Split"
    )
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission."
    )
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s "
        f"commitment={args.commitment} "
        f"pump_writer=ordered_microbatch "
        f"batch_size={args.pump_batch_size} "
        f"batch_max_wait_ms={args.pump_batch_max_wait_ms} "
        f"pumpswap_workers={args.pumpswap_workers} "
        f"pumpswap_prepare_workers={args.pumpswap_radar_workers} "
        f"pumpswap_finalize_workers=1 "
        f"concurrent_resolutions={args.max_concurrent_resolutions} "
        f"max_hydrations={args.max_hydrations} "
        f"queue_size={args.queue_size}"
    )
    print(
        "v11 prepares transaction/history reads + detector compute in parallel after "
        "persistence, then preserves per-asset ingress FIFO only for trigger/episode "
        "finalization. No detector or provider-policy tuning is applied."
    )

    try:
        asyncio.run(
            run_smoke_v11(
                run_key=args.run_key,
                duration_seconds=args.duration_seconds,
                commitment=args.commitment,
                max_hydrations=args.max_hydrations,
                rpc_timeout_seconds=args.rpc_timeout_seconds,
                pump_batch_size=args.pump_batch_size,
                pump_batch_max_wait_ms=args.pump_batch_max_wait_ms,
                pumpswap_workers=args.pumpswap_workers,
                pumpswap_radar_workers=args.pumpswap_radar_workers,
                max_concurrent_resolutions=args.max_concurrent_resolutions,
                queue_size=args.queue_size,
            )
        )
    finally:
        _print_replay_telemetry(args.run_key)


if __name__ == "__main__":
    main()
