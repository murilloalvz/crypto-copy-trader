from __future__ import annotations

import argparse
import asyncio

from src.pumpswap_opportunistic_prefetch_v53 import (
    OpportunisticPumpSwapIngressPrefetchV53,
)
from src.pumpswap_resolver_wait_trace_v53 import TracedDeadlineBoundedResolverV53
import unified_market_latency_smoke_v19 as v19
import unified_market_route_research_smoke_v49 as v49
import unified_market_route_research_smoke_v52 as v52


_BASE_V52_RUN_SMOKE = v52.run_smoke_v52


def _short_pool(pool: str) -> str:
    text = str(pool)
    return text if len(text) <= 12 else f"{text[:10]}…"


async def run_smoke_v53(**kwargs) -> None:
    """Run v52 with opportunistic-only ingress prefetch and resolver wait telemetry.

    The authoritative resolver path remains the inherited v52/v41/v33/v32 path. Only optional v49
    ingress prefetch admission changes: after a free causal-cache check, speculative work is not
    allowed to join a busy per-pool lock or saturated expensive-resolution semaphore. This prevents
    optional prefetch from queueing ahead of causal normalization demand while preserving all
    canonical resolver, persistence, reservation, FIFO, detector and research semantics.
    """

    original_v52_resolver = v52.DeadlineBoundedParallelHedgedResolverV52
    original_v49_prefetcher = v49.PumpSwapIngressPrefetchV49
    TracedDeadlineBoundedResolverV53.last_instance = None
    OpportunisticPumpSwapIngressPrefetchV53.last_instance = None
    v52.DeadlineBoundedParallelHedgedResolverV52 = TracedDeadlineBoundedResolverV53
    v49.PumpSwapIngressPrefetchV49 = OpportunisticPumpSwapIngressPrefetchV53
    try:
        await _BASE_V52_RUN_SMOKE(**kwargs)
    finally:
        v52.DeadlineBoundedParallelHedgedResolverV52 = original_v52_resolver
        v49.PumpSwapIngressPrefetchV49 = original_v49_prefetcher

    resolver = TracedDeadlineBoundedResolverV53.last_instance
    prefetcher = OpportunisticPumpSwapIngressPrefetchV53.last_instance
    print("\nV53 OPPORTUNISTIC PREFETCH / RESOLVER WAIT DIAGNOSTIC")
    if resolver is None:
        print("v53_resolver_instance=missing")
    else:
        snapshot = resolver.resolver_wait_snapshot_v53()
        print(
            f"resolver_pool_lock_waits={snapshot.pool_lock_waits} "
            f"resolver_capacity_waits={snapshot.capacity_waits} "
            f"demand_capacity_waiters_high_water={snapshot.demand_capacity_waiters_high_water} "
            f"prefetch_capacity_waiters_high_water={snapshot.prefetch_capacity_waiters_high_water}"
        )
        print(
            "demand_resolve_ms "
            f"{v19._latency_summary_ms(list(snapshot.demand_resolve_seconds))}"
        )
        print(
            "prefetch_resolve_ms "
            f"{v19._latency_summary_ms(list(snapshot.prefetch_resolve_seconds))}"
        )
        print(
            "demand_pool_lock_wait_ms "
            f"{v19._latency_summary_ms(list(snapshot.demand_pool_lock_wait_seconds))}"
        )
        print(
            "prefetch_pool_lock_wait_ms "
            f"{v19._latency_summary_ms(list(snapshot.prefetch_pool_lock_wait_seconds))}"
        )
        print(
            "demand_resolution_capacity_wait_ms "
            f"{v19._latency_summary_ms(list(snapshot.demand_capacity_wait_seconds))}"
        )
        print(
            "prefetch_resolution_capacity_wait_ms "
            f"{v19._latency_summary_ms(list(snapshot.prefetch_capacity_wait_seconds))}"
        )
        if snapshot.hot_pool_lock_wait_seconds:
            print(
                "v53_hot_pool_lock_waits "
                + " ".join(
                    f"{_short_pool(pool)}:wait_total_ms={total * 1000.0:.1f},waits={count}"
                    for pool, total, count in snapshot.hot_pool_lock_wait_seconds
                )
            )

    if prefetcher is None:
        print("v53_prefetcher_instance=missing")
    else:
        prefetch = prefetcher.snapshot_v53()
        print(
            f"v53_prefetch_notifications={prefetch.notifications_seen} "
            f"candidate_pools={prefetch.candidate_pools} scheduled={prefetch.scheduled} "
            f"coalesced_inflight={prefetch.coalesced_inflight} admitted={prefetch.admitted} "
            f"skipped_capacity={prefetch.skipped_capacity} "
            f"skipped_pool_busy={prefetch.skipped_pool_busy} "
            f"completed_available={prefetch.completed_available} "
            f"completed_unresolved={prefetch.completed_unresolved} failed={prefetch.failed} "
            f"active_after_drain={prefetch.active}"
        )

    print(
        "v53_note=only speculative v49 ingress prefetch admission changes. A causal-cache hit remains "
        "free; otherwise prefetch skips instead of queueing when the same pool is already resolving "
        "or the inherited expensive-resolution semaphore has no immediate slot. Authoritative "
        "normalization still uses resolver.resolve unchanged. Resolver lock/capacity telemetry is "
        "observational and does not alter ordering or budgets."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = v52.build_parser()
    parser.description = (
        "v53 systems-only route smoke: v52 wall deadline plus opportunistic-only PumpSwap ingress "
        "prefetch and resolver wait-stage telemetry"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.duration_seconds <= v19.MAX_SMOKE_SECONDS:
        raise SystemExit(
            f"--duration-seconds must be between 1 and {v19.MAX_SMOKE_SECONDS}"
        )

    print("Crypto Copy Trader — Unified Market Route-Only Research Smoke v53")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — v52 deadline + opportunistic prefetch admission; "
        "no forward economic collection, signing, transaction submission or live funds."
    )
    asyncio.run(
        run_smoke_v53(
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
