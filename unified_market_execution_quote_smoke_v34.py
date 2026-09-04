from __future__ import annotations

import argparse
import asyncio

from src.pumpswap_demoting_scheduler_v34 import DemotingReadyAssetSchedulerV34
import unified_market_execution_quote_smoke_v31 as v31
import unified_market_execution_quote_smoke_v33 as v33
import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v27 as v27
import unified_market_latency_smoke_v30 as v30


async def run_smoke_v34(**kwargs) -> None:
    """Run v33 with proof-based demotion of pending stateful continuation followers.

    v27 already rechecks the immutable run-local episode cache at finalize time. v34 moves
    that same proof one step earlier for jobs that are still pending in the per-asset FIFO:
    after an opener establishes the episode, pending submitted jobs that the same cache proves
    are continuation-only are converted to causal skips. Tickets remain ordered and ambiguous,
    late-earlier or different-window work remains stateful.
    """

    original_cache_class = v27._EpisodeContinuationCache
    original_scheduler_class = v19.ReadyAssetScheduler

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

    v27._EpisodeContinuationCache = TrackingEpisodeCache
    v19.ReadyAssetScheduler = ConfiguredDemotingScheduler
    try:
        await v33.run_smoke_v33(**kwargs)
    finally:
        v19.ReadyAssetScheduler = original_scheduler_class
        v27._EpisodeContinuationCache = original_cache_class

    scheduler = ConfiguredDemotingScheduler.last_instance
    print("\nV34 PROOF-BASED STATEFUL FOLLOWER DEMOTION DIAGNOSTIC")
    if scheduler is None:
        print("scheduler_instance=missing")
    else:
        print(
            f"demoted_pending_jobs={scheduler.demoted_pending_jobs} "
            f"demoted_pending_tickets={scheduler.demoted_pending_tickets} "
            f"demotion_wait_ms={v19._latency_summary_ms(scheduler.demotion_wait_seconds)}"
        )
    print(
        "v34 changes no detector threshold, episode window, trigger identity, reservation ticket, "
        "or FIFO rule. It only converts already-submitted pending jobs to causal skips after the "
        "same v27 episode cache proves they can no longer mutate episode state."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market v34 quote smoke with proof-based PumpSwap follower demotion"
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
    parser.add_argument("--max-quote-episodes", type=int, default=12)
    parser.add_argument("--quote-workers", type=int, default=2)
    parser.add_argument("--jupiter-timeout-seconds", type=int, default=5)
    parser.add_argument("--quote-notional-usd", type=float, default=25.0)
    parser.add_argument("--quote-slippage-bps", type=int, default=100)
    parser.add_argument("--hydration-batch-size", type=int, default=64)
    parser.add_argument("--hydration-batch-max-wait-ms", type=int, default=5)
    parser.add_argument("--hedge-endpoints", type=int, default=2)
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
    if args.hydration_batch_size <= 0 or args.hedge_endpoints <= 0:
        parser.error("hydration batch size and hedge endpoints must be positive")
    if args.hydration_batch_max_wait_ms < 0:
        parser.error("hydration-batch-max-wait-ms cannot be negative")
    if args.max_quote_episodes <= 0 or args.quote_workers <= 0:
        parser.error("quote counts must be positive")
    if args.jupiter_timeout_seconds <= 0 or args.quote_notional_usd <= 0:
        parser.error("quote timeout/notional must be positive")
    if not 0 <= args.quote_slippage_bps <= 10_000:
        parser.error("quote-slippage-bps must be between 0 and 10000")

    print("Crypto Copy Trader — Unified Market Execution Quote Smoke v34")
    print("Mode: PAPER / RESEARCH / READ ONLY — proof-based FIFO demotion + Jupiter order assembly; no signing/execute.")
    asyncio.run(
        run_smoke_v34(
            hydration_batch_size=args.hydration_batch_size,
            hydration_batch_max_wait_ms=args.hydration_batch_max_wait_ms,
            hedge_endpoints=args.hedge_endpoints,
            max_quote_episodes=args.max_quote_episodes,
            quote_workers=args.quote_workers,
            jupiter_timeout_seconds=args.jupiter_timeout_seconds,
            quote_notional_usd=args.quote_notional_usd,
            quote_slippage_bps=args.quote_slippage_bps,
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
