from __future__ import annotations

import argparse
import asyncio

from src.pumpswap_demand_only_prefetch_v54 import (
    DemandOnlyPumpSwapIngressPrefetchV54,
)
import unified_market_latency_smoke_v19 as v19
import unified_market_route_research_smoke_v53 as v53


_BASE_V53_RUN_SMOKE = v53.run_smoke_v53


async def run_smoke_v54(**kwargs) -> None:
    """Run v53 with ingress prefetch reduced to observation-only diagnostics.

    v54 leaves the authoritative v53/v52 resolver, cache/history/store logic, batching, hedging,
    hydration budget, reservation ordering, FIFO, detector and route-research semantics unchanged.
    It changes only the optional ingress prefetch component so speculative work cannot acquire a
    per-pool resolver lock or expensive-resolution capacity ahead of causal normalization demand.
    """

    original_prefetch_class = v53.OpportunisticPumpSwapIngressPrefetchV53
    DemandOnlyPumpSwapIngressPrefetchV54.last_instance = None
    v53.OpportunisticPumpSwapIngressPrefetchV53 = DemandOnlyPumpSwapIngressPrefetchV54
    try:
        await _BASE_V53_RUN_SMOKE(**kwargs)
    finally:
        v53.OpportunisticPumpSwapIngressPrefetchV53 = original_prefetch_class

    prefetcher = DemandOnlyPumpSwapIngressPrefetchV54.last_instance
    print("\nV54 DEMAND-ONLY RESOLVER ADMISSION DIAGNOSTIC")
    if prefetcher is None:
        print("v54_prefetcher_instance=missing")
    else:
        snapshot = prefetcher.snapshot_v54()
        print(
            f"notifications_seen={snapshot.notifications_seen} "
            f"candidate_pools={snapshot.candidate_pools} scheduled={snapshot.scheduled} "
            f"skipped_speculative={snapshot.skipped_speculative} active_after_drain={snapshot.active}"
        )
    print(
        "v54_note=ingress prefetch is observation-only. It does not call resolver.resolve, acquire "
        "per-pool locks or resolution capacity, consume hydration budget, persist pool mappings, "
        "reserve assets or create detector evidence. Authoritative normalization remains unchanged."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = v53.build_parser()
    parser.description = (
        "v54 systems-only route smoke: v53/v52 authoritative resolver path with speculative "
        "PumpSwap ingress resolver admission disabled"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.duration_seconds <= v19.MAX_SMOKE_SECONDS:
        raise SystemExit(
            f"--duration-seconds must be between 1 and {v19.MAX_SMOKE_SECONDS}"
        )

    print("Crypto Copy Trader — Unified Market Route-Only Research Smoke v54")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — authoritative demand-only PumpSwap resolution; "
        "no forward economic collection, signing, transaction submission or live funds."
    )
    asyncio.run(
        run_smoke_v54(
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
