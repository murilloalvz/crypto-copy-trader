from __future__ import annotations

import argparse
import asyncio

from src.pumpswap_eager_demoting_scheduler_v42 import EagerDemotingReadyAssetSchedulerV42
import unified_market_execution_quote_smoke_v31 as v31
import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v30 as v30
import unified_market_onchain_hazard_smoke_v37 as v37
import unified_market_route_research_smoke_v41 as v41


async def run_smoke_v42(**kwargs) -> None:
    """Run v41 with eager proof-based demotion of already-pending continuation followers.

    v41 removed the serialized hydration transport bottleneck. Its live residual tail was dominated
    by hot-asset stateful FIFO waits. v42 changes only *when* the existing v34 proof is evaluated:
    besides completion-time demotion, each new submit first rechecks older pending followers against
    the immutable run-local episode cache. Work still considered stateful remains strict FIFO.
    """

    original_scheduler = v37.DemotingReadyAssetSchedulerV34
    EagerDemotingReadyAssetSchedulerV42.last_instance = None
    v37.DemotingReadyAssetSchedulerV34 = EagerDemotingReadyAssetSchedulerV42
    try:
        await v41.run_smoke_v41(**kwargs)
    finally:
        v37.DemotingReadyAssetSchedulerV34 = original_scheduler

    scheduler = EagerDemotingReadyAssetSchedulerV42.last_instance
    print("\nV42 EAGER PROOF-BASED CONTINUATION DEMOTION DIAGNOSTIC")
    if scheduler is None:
        print("eager_scheduler_instance=missing")
    else:
        print(
            f"eager_submit_demote_passes={scheduler.eager_submit_demote_passes} "
            f"eager_submit_demoted_jobs={scheduler.eager_submit_demoted_jobs} "
            f"eager_submit_demoted_tickets={scheduler.eager_submit_demoted_tickets} "
            f"total_demoted_pending_jobs={scheduler.demoted_pending_jobs} "
            f"total_demoted_pending_tickets={scheduler.demoted_pending_tickets} "
            f"demoted_finalizer_acks_pending={scheduler.demoted_finalizer_acks_pending}"
        )
        print(
            f"demotion_wait_ms {v19._latency_summary_ms(scheduler.demotion_wait_seconds)}"
        )
    print(
        "v42_note=eager submit-time demotion uses the exact v34/v27 continuation proof over pending "
        "work only. Ready/running/ambiguous/late-earlier work is never demoted; detector, episode, "
        "reservation, FIFO, replay and as-of semantics are unchanged."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fresh v42 route-only research smoke with v41 parallel hydration and eager proven "
            "continuation demotion"
        )
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
    parser.add_argument("--hydration-batch-workers", type=int, default=8)
    parser.add_argument("--max-hazard-episodes", type=int, default=12)
    parser.add_argument("--hazard-workers", type=int, default=2)
    parser.add_argument("--hazard-rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--max-research-episodes", type=int, default=12)
    parser.add_argument("--research-workers", type=int, default=2)
    parser.add_argument("--hazard-wait-timeout-seconds", type=int, default=20)
    parser.add_argument("--jupiter-timeout-seconds", type=int, default=5)
    parser.add_argument("--research-notional-usd", type=float, default=25.0)
    parser.add_argument("--research-slippage-bps", type=int, default=100)
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
    if args.hydration_batch_workers * args.hedge_endpoints > args.max_concurrent_resolutions:
        parser.error(
            "hydration-batch-workers * hedge-endpoints must not exceed max-concurrent-resolutions"
        )

    print("Crypto Copy Trader — Unified Market Route-Only Research Smoke v42")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — v41 bounded parallel hydration + eager proof-based "
        "pending continuation demotion; no taker, signing, execute, transfer or official decision freeze."
    )
    asyncio.run(
        run_smoke_v42(
            max_research_episodes=args.max_research_episodes,
            research_workers=args.research_workers,
            hazard_wait_timeout_seconds=args.hazard_wait_timeout_seconds,
            jupiter_timeout_seconds=args.jupiter_timeout_seconds,
            research_notional_usd=args.research_notional_usd,
            research_slippage_bps=args.research_slippage_bps,
            hydration_batch_workers=args.hydration_batch_workers,
            max_hazard_episodes=args.max_hazard_episodes,
            hazard_workers=args.hazard_workers,
            hazard_rpc_timeout_seconds=args.hazard_rpc_timeout_seconds,
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
