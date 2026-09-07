from __future__ import annotations

import argparse
import asyncio

from src.pumpswap_deadline_hedged_resolver_v52 import (
    DeadlineBoundedParallelHedgedResolverV52,
)
import unified_market_latency_smoke_v19 as v19
import unified_market_route_research_smoke_v41 as v41
import unified_market_route_research_smoke_v51 as v51


_BASE_V51_RUN_SMOKE = v51.run_smoke_v51


async def run_smoke_v52(**kwargs) -> None:
    """Run v51 with a true wall-clock bound on PumpSwap hedged unknown-pool RPC batches.

    The configured resolver timeout is reused verbatim; no new threshold is introduced. All v49
    prefetch, v50 tracing, v51 ready-priority, global reservation ordering, per-asset FIFO and
    detector/research semantics remain unchanged.
    """

    original_parallel_resolver = v41.ParallelHedgedBatchedBoundedResolverV41
    DeadlineBoundedParallelHedgedResolverV52.last_instance = None
    v41.ParallelHedgedBatchedBoundedResolverV41 = (
        DeadlineBoundedParallelHedgedResolverV52
    )
    try:
        await _BASE_V51_RUN_SMOKE(**kwargs)
    finally:
        v41.ParallelHedgedBatchedBoundedResolverV41 = original_parallel_resolver

    resolver = DeadlineBoundedParallelHedgedResolverV52.last_instance
    print("\nV52 PUMPSWAP HEDGED RPC WALL-DEADLINE DIAGNOSTIC")
    if resolver is None:
        print("v52_resolver_instance=missing")
        return

    snapshot = resolver.hedge_deadline_snapshot_v52()
    print(
        f"hedge_wall_deadline_seconds={snapshot.wall_deadline_seconds:.3f} "
        f"hedge_wall_deadline_expirations={snapshot.deadline_expirations} "
        f"hedged_batch_calls={resolver.hedged_batch_calls} "
        f"hedged_endpoint_requests={resolver.hedged_endpoint_requests} "
        f"hedged_all_failed={resolver.hedged_all_failed} "
        f"network_batch_calls={resolver.network_batch_calls}"
    )
    print(
        f"hedge_fetch_ms {v19._latency_summary_ms(list(snapshot.fetch_seconds))}"
    )
    print(
        "v52_note=the wall deadline equals the already-configured PumpSwap RPC timeout. "
        "No global reservation/FIFO/detector/provider/economic rule changes; a batch without a "
        "valid identity inside that deadline follows the existing explicit unresolved path."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = v51.build_parser()
    parser.description = (
        "v52 systems-only route smoke with v51 stateful priority plus a true hedged RPC wall deadline"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.duration_seconds <= v19.MAX_SMOKE_SECONDS:
        raise SystemExit(
            f"--duration-seconds must be between 1 and {v19.MAX_SMOKE_SECONDS}"
        )

    print("Crypto Copy Trader — Unified Market Route-Only Research Smoke v52")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — v51 scheduling + v52 configured RPC wall deadline; "
        "no forward economic collection, signing, transaction submission or live funds."
    )
    asyncio.run(
        run_smoke_v52(
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
