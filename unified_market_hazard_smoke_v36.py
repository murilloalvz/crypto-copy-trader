from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import time

from src.config import settings
from src.market_opportunity_episode_store import get_market_opportunity_episode
from src.opportunity_token_hazard import (
    SOLANA_TRACKER_HAZARD_PROVIDER,
    SOLANA_TRACKER_HAZARD_PURPOSE,
    SolanaTrackerTokenHazardProbe,
)
from src.pumpswap_demoting_scheduler_v34 import DemotingReadyAssetSchedulerV34
from src.pumpswap_hedged_batched_resolver_v33 import HedgedBatchedBoundedResolverV33
import unified_market_execution_quote_smoke_v31 as v31
import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v27 as v27
import unified_market_latency_smoke_v30 as v30


@dataclass(frozen=True)
class HazardJob:
    episode_key: str
    enqueued_monotonic: float


async def run_smoke_v36(
    *,
    max_hazard_episodes: int,
    hazard_workers: int,
    hazard_timeout_seconds: int,
    hazard_max_attempts: int,
    hydration_batch_size: int,
    hydration_batch_max_wait_ms: int,
    hedge_endpoints: int,
    default_io_workers: int,
    **kwargs,
) -> None:
    """Run the proven v34 market path plus an isolated causal token-hazard queue.

    Jupiter is intentionally absent from this smoke. The purpose is to validate provider
    observability while funded executable assembly is externally blocked, without changing detector
    thresholds, episode semantics or the final gate order.
    """

    if min(max_hazard_episodes, hazard_workers, hazard_timeout_seconds, hazard_max_attempts) <= 0:
        raise ValueError("hazard smoke counts/timeouts must be positive")
    if hydration_batch_size <= 0 or hedge_endpoints <= 0:
        raise ValueError("hydration batch size and hedge endpoints must be positive")
    if hydration_batch_max_wait_ms < 0:
        raise ValueError("hydration_batch_max_wait_ms cannot be negative")

    original_cache_class = v27._EpisodeContinuationCache
    original_scheduler_class = v19.ReadyAssetScheduler
    original_resolver_class = v19.BoundedConcurrentResolver
    original_admit = v19.admit_opportunity_episode

    class TrackingEpisodeCache(original_cache_class):
        last_instance = None

        def __init__(self):
            super().__init__()
            TrackingEpisodeCache.last_instance = self

    class ConfiguredDemotingScheduler(DemotingReadyAssetSchedulerV34):
        last_instance = None

        def __init__(self):
            def should_remain_stateful(payload) -> bool:
                prepared = getattr(payload, "prepared", None)
                cache = TrackingEpisodeCache.last_instance
                if prepared is None or cache is None:
                    return True
                return v27._prepared_requires_stateful_episode(prepared, cache)

            super().__init__(should_remain_stateful=should_remain_stateful)
            ConfiguredDemotingScheduler.last_instance = self

    class ConfiguredHedgedResolver(HedgedBatchedBoundedResolverV33):
        def __init__(self, *args, **resolver_kwargs):
            super().__init__(
                *args,
                hydration_batch_size=hydration_batch_size,
                hydration_batch_max_wait_ms=hydration_batch_max_wait_ms,
                hedge_endpoints=hedge_endpoints,
                **resolver_kwargs,
            )

    hazard_queue: asyncio.Queue[HazardJob] = asyncio.Queue(maxsize=max_hazard_episodes)
    counters: Counter[str] = Counter()
    latencies: list[float] = []
    selected_episode_keys: set[str] = set()
    probe = SolanaTrackerTokenHazardProbe(
        api_key=settings.solana_tracker_api_key,
        timeout_seconds=hazard_timeout_seconds,
        max_attempts=hazard_max_attempts,
    )
    executor = ThreadPoolExecutor(
        max_workers=hazard_workers,
        thread_name_prefix="solana-tracker-hazard-v36",
    )

    def admit_and_enqueue(**admit_kwargs) -> bool:
        admitted = original_admit(**admit_kwargs)
        if not admitted:
            counters["admission_replays"] += 1
            return False
        counters["new_admissions"] += 1
        episode_key = str(admit_kwargs["episode_key"])
        if len(selected_episode_keys) >= max_hazard_episodes:
            counters["not_selected_after_predeclared_cap"] += 1
            return True
        if episode_key in selected_episode_keys:
            raise RuntimeError("new episode admission unexpectedly selected twice for hazard")
        selected_episode_keys.add(episode_key)
        hazard_queue.put_nowait(HazardJob(episode_key, time.monotonic()))
        counters["selected_for_hazard"] += 1
        return True

    async def hazard_worker(index: int) -> None:
        loop = asyncio.get_running_loop()
        while True:
            job = await hazard_queue.get()
            try:
                episode = get_market_opportunity_episode(job.episode_key)
                if episode is None:
                    counters["missing_episode_after_admission"] += 1
                    continue
                started = time.monotonic()
                result = await loop.run_in_executor(executor, probe.capture, episode)
                finished = time.monotonic()
                latencies.append(finished - job.enqueued_monotonic)
                counters[f"status_{result.attempt.status.lower()}"] += 1
                if result.reused_attempt:
                    counters["reused_attempts"] += 1
                if result.evidence.observed_at is not None:
                    if result.evidence.observed_at < episode.first_trigger_observed_at:
                        counters["causal_clock_violations"] += 1
                if result.evidence.status == "AVAILABLE":
                    counters["hazard_evidence_available"] += 1
                print(
                    f"[hazard-episode] worker={index} episode={job.episode_key[-12:]} "
                    f"status={result.attempt.status} latency_ms={(finished-started)*1000.0:.1f} "
                    f"risk_score={result.evidence.risk_score} rugged={result.evidence.rugged} "
                    f"quality_flags={len(result.evidence.data_quality_flags)}"
                )
            except Exception as exc:
                counters["hazard_worker_errors"] += 1
                print(
                    f"[hazard-episode-error] worker={index} episode={job.episode_key[-12:]} "
                    f"error={type(exc).__name__}:{exc}"
                )
            finally:
                hazard_queue.task_done()

    workers = [
        asyncio.create_task(hazard_worker(index), name=f"hazard-v36-{index}")
        for index in range(hazard_workers)
    ]

    HedgedBatchedBoundedResolverV33.last_instance = None
    v27._EpisodeContinuationCache = TrackingEpisodeCache
    v19.ReadyAssetScheduler = ConfiguredDemotingScheduler
    v19.BoundedConcurrentResolver = ConfiguredHedgedResolver
    v19.admit_opportunity_episode = admit_and_enqueue
    try:
        await v30.run_smoke_v30(default_io_workers=default_io_workers, **kwargs)
        await hazard_queue.join()
    finally:
        v19.admit_opportunity_episode = original_admit
        v19.BoundedConcurrentResolver = original_resolver_class
        v19.ReadyAssetScheduler = original_scheduler_class
        v27._EpisodeContinuationCache = original_cache_class
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        executor.shutdown(wait=True, cancel_futures=False)

    scheduler = ConfiguredDemotingScheduler.last_instance
    resolver = HedgedBatchedBoundedResolverV33.last_instance
    selected = counters["selected_for_hazard"]
    terminal_statuses = (
        "available",
        "unavailable",
        "config_missing",
        "provider_error",
        "metadata_error",
        "normalization_error",
    )
    terminal = sum(counters[f"status_{status}"] for status in terminal_statuses)
    coverage = 100.0 * terminal / selected if selected else 0.0

    print("\nV36 SOLANA TRACKER CAUSAL TOKEN HAZARD DIAGNOSTIC")
    print(
        f"provider={SOLANA_TRACKER_HAZARD_PROVIDER} purpose={SOLANA_TRACKER_HAZARD_PURPOSE} "
        f"new_admissions={counters['new_admissions']} selected={selected} "
        f"predeclared_cap={max_hazard_episodes} hazard_workers={hazard_workers}"
    )
    print(
        f"statuses={{'AVAILABLE': {counters['status_available']}, "
        f"'UNAVAILABLE': {counters['status_unavailable']}, "
        f"'CONFIG_MISSING': {counters['status_config_missing']}, "
        f"'PROVIDER_ERROR': {counters['status_provider_error']}, "
        f"'METADATA_ERROR': {counters['status_metadata_error']}, "
        f"'NORMALIZATION_ERROR': {counters['status_normalization_error']}}} "
        f"terminal_coverage_pct={coverage:.1f}%"
    )
    print(
        f"hazard_evidence_available={counters['hazard_evidence_available']} "
        f"reused_attempts={counters['reused_attempts']} "
        f"hazard_worker_errors={counters['hazard_worker_errors']} "
        f"causal_clock_violations={counters['causal_clock_violations']} "
        f"not_selected_after_predeclared_cap={counters['not_selected_after_predeclared_cap']}"
    )
    print(f"episode_to_hazard_terminal_ms {v19._latency_summary_ms(latencies)}")
    if not selected:
        classification = "INCONCLUSIVE_NO_SAMPLE"
    elif (
        terminal == selected
        and counters["status_config_missing"] == 0
        and counters["hazard_worker_errors"] == 0
        and counters["causal_clock_violations"] == 0
        and counters["reused_attempts"] == 0
        and counters["hazard_evidence_available"] > 0
    ):
        classification = "PASS_CAUSAL_HAZARD_PROVIDER"
    else:
        classification = "FAIL_CAUSAL_HAZARD_PROVIDER"
    print(f"hazard_provider_classification={classification}")

    print("\nV36 RETAINED V34/V33 DIAGNOSTICS")
    if scheduler is None:
        print("v34_scheduler_instance=missing")
    else:
        print(
            f"demoted_pending_jobs={scheduler.demoted_pending_jobs} "
            f"demoted_pending_tickets={scheduler.demoted_pending_tickets} "
            f"demoted_finalizer_acks_pending={scheduler.demoted_finalizer_acks_pending} "
            f"demotion_wait_ms={v19._latency_summary_ms(scheduler.demotion_wait_seconds)}"
        )
    if resolver is None:
        print("v33_resolver_instance=missing")
    else:
        print(
            f"pool_hydrations={resolver.network_hydration_calls} "
            f"successful_batches={resolver.network_batch_calls} "
            f"endpoint_requests={resolver.hedged_endpoint_requests} "
            f"all_hedges_failed={resolver.hedged_all_failed} "
            f"budget_skips={resolver.hydration_budget_skips}"
        )
    print(
        "v36 adds only an off-path hazard queue after first-time episode admission. It does not "
        "call Jupiter, change detector thresholds, freeze decision_as_of, schedule official forward "
        "outcomes, sign transactions or move funds. The v30 11-gate latency summary printed above "
        "must still be evaluated independently in the same run."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market v36 hazard-only smoke retaining the v34 latency path"
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1500)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-batch-size", type=int, default=32)
    parser.add_argument("--pump-batch-max-wait-ms", type=int, default=25)
    parser.add_argument("--pump-prepare-workers", type=int, default=v31.PASS_PUMP_PREPARE_WORKERS)
    parser.add_argument("--pumpswap-workers", type=int, default=v31.PASS_PUMPSWAP_WORKERS)
    parser.add_argument("--pumpswap-prepare-submitters", type=int, default=v31.PASS_PUMPSWAP_PREPARE_SUBMITTERS)
    parser.add_argument("--pumpswap-prepare-executor-workers", type=int, default=v31.PASS_PUMPSWAP_PREPARE_EXECUTOR_WORKERS)
    parser.add_argument("--pumpswap-writer-batch-size", type=int, default=32)
    parser.add_argument("--pumpswap-writer-batch-max-wait-ms", type=int, default=10)
    parser.add_argument("--max-concurrent-resolutions", type=int, default=18)
    parser.add_argument("--queue-size", type=int, default=5000)
    parser.add_argument("--continuation-batch-size", type=int, default=32)
    parser.add_argument("--continuation-batch-max-wait-ms", type=int, default=5)
    parser.add_argument("--default-io-workers", type=int, default=v31.PASS_DEFAULT_IO_WORKERS)
    parser.add_argument("--hydration-batch-size", type=int, default=64)
    parser.add_argument("--hydration-batch-max-wait-ms", type=int, default=5)
    parser.add_argument("--hedge-endpoints", type=int, default=2)
    parser.add_argument("--max-hazard-episodes", type=int, default=12)
    parser.add_argument("--hazard-workers", type=int, default=2)
    parser.add_argument("--hazard-timeout-seconds", type=int, default=8)
    parser.add_argument("--hazard-max-attempts", type=int, default=1)
    args = parser.parse_args()

    if not 1 <= args.duration_seconds <= v19.MAX_SMOKE_SECONDS:
        parser.error(f"duration-seconds must be between 1 and {v19.MAX_SMOKE_SECONDS}")
    try:
        v30.validate_capacity_profile(
            pumpswap_workers=args.pumpswap_workers,
            pump_prepare_workers=args.pump_prepare_workers,
            pumpswap_prepare_submitters=args.pumpswap_prepare_submitters,
            pumpswap_prepare_executor_workers=args.pumpswap_prepare_executor_workers,
            default_io_workers=args.default_io_workers,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if min(
        args.hydration_batch_size,
        args.hedge_endpoints,
        args.max_hazard_episodes,
        args.hazard_workers,
        args.hazard_timeout_seconds,
        args.hazard_max_attempts,
    ) <= 0:
        parser.error("hydration/hazard counts and timeouts must be positive")
    if args.hydration_batch_max_wait_ms < 0:
        parser.error("hydration-batch-max-wait-ms cannot be negative")

    print("Crypto Copy Trader — Unified Market Hazard Smoke v36")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — v34 market path + Solana Tracker token hazard; "
        "no Jupiter order, signing, execute or transfer."
    )
    asyncio.run(
        run_smoke_v36(
            max_hazard_episodes=args.max_hazard_episodes,
            hazard_workers=args.hazard_workers,
            hazard_timeout_seconds=args.hazard_timeout_seconds,
            hazard_max_attempts=args.hazard_max_attempts,
            hydration_batch_size=args.hydration_batch_size,
            hydration_batch_max_wait_ms=args.hydration_batch_max_wait_ms,
            hedge_endpoints=args.hedge_endpoints,
            default_io_workers=args.default_io_workers,
            run_key=args.run_key,
            duration_seconds=args.duration_seconds,
            commitment=args.commitment,
            max_hydrations=args.max_hydrations,
            rpc_timeout_seconds=args.rpc_timeout_seconds,
            pump_batch_size=args.pump_batch_size,
            pump_batch_max_wait_ms=args.pump_batch_max_wait_ms,
            pump_prepare_workers=args.pump_prepare_workers,
            pumpswap_workers=args.pumpswap_workers,
            pumpswap_prepare_submitters=args.pumpswap_prepare_submitters,
            pumpswap_prepare_executor_workers=args.pumpswap_prepare_executor_workers,
            pumpswap_writer_batch_size=args.pumpswap_writer_batch_size,
            pumpswap_writer_batch_max_wait_ms=args.pumpswap_writer_batch_max_wait_ms,
            max_concurrent_resolutions=args.max_concurrent_resolutions,
            queue_size=args.queue_size,
            continuation_batch_size=args.continuation_batch_size,
            continuation_batch_max_wait_ms=args.continuation_batch_max_wait_ms,
        )
    )


if __name__ == "__main__":
    main()
