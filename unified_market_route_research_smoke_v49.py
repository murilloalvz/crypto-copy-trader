from __future__ import annotations

import argparse
import asyncio

from src.pumpswap_ingress_prefetch_v49 import (
    PumpSwapIngressPrefetchV49,
    iter_pumpswap_with_ingress_prefetch_v49,
)
from src.pumpswap_parallel_batched_resolver_v41 import ParallelHedgedBatchedBoundedResolverV41
import unified_market_execution_quote_smoke_v31 as v31
import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v30 as v30
import unified_market_route_research_smoke_v42 as v42


V49_PUMP_PREPARE_WORKERS = 20


async def run_smoke_v49(**kwargs) -> None:
    """Run frozen v42 semantics with ingress-ordered pool identity prefetch.

    The only behavioral change is when immutable PumpSwap pool identity resolution begins.
    Notification content/order, detector thresholds, persistence, reservation ordering, FIFO,
    replay/as-of rules, route-only research semantics and provider calls remain authoritative in
    the existing v42 path. Prefetch uses that same resolver, so per-pool single-flight and the
    existing network budget prevent duplicate expensive work.
    """

    original_stream_factory = v19.iter_pumpswap_log_notifications
    prefetcher = PumpSwapIngressPrefetchV49()

    def _wrapped_stream_factory(**stream_kwargs):
        return iter_pumpswap_with_ingress_prefetch_v49(
            base_factory=original_stream_factory,
            resolver_getter=lambda: ParallelHedgedBatchedBoundedResolverV41.last_instance,
            prefetcher=prefetcher,
            **stream_kwargs,
        )

    v19.iter_pumpswap_log_notifications = _wrapped_stream_factory
    try:
        await v42.run_smoke_v42(**kwargs)
    finally:
        v19.iter_pumpswap_log_notifications = original_stream_factory
        await prefetcher.drain(
            timeout_seconds=float(kwargs.get("rpc_timeout_seconds", 3)) + 2.0
        )

    snapshot = prefetcher.snapshot()
    print("\nV49 PUMPSWAP INGRESS IDENTITY PREFETCH DIAGNOSTIC")
    print(
        f"notifications_seen={snapshot.notifications_seen} "
        f"candidate_pools={snapshot.candidate_pools} scheduled={snapshot.scheduled} "
        f"coalesced_inflight={snapshot.coalesced_inflight} "
        f"completed_available={snapshot.completed_available} "
        f"completed_unresolved={snapshot.completed_unresolved} failed={snapshot.failed} "
        f"active_after_drain={snapshot.active}"
    )
    print(
        "v49_note=prefetch begins immutable pool identity resolution at stream ingress only. "
        "Canonical normalization/persistence, strict reservation order, FIFO, detector and "
        "research semantics remain unchanged; the same resolver budget/single-flight owns RPC work."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "v49 systems stabilization smoke: v42 route-only path with ingress pool prefetch "
            "and measured Pump prepare capacity"
        )
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1500)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-batch-size", type=int, default=32)
    parser.add_argument("--pump-batch-max-wait-ms", type=int, default=25)
    parser.add_argument("--pump-prepare-workers", type=int, default=V49_PUMP_PREPARE_WORKERS)
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
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.duration_seconds <= v19.MAX_SMOKE_SECONDS:
        raise SystemExit(
            f"--duration-seconds must be between 1 and {v19.MAX_SMOKE_SECONDS}"
        )
    try:
        v30.validate_capacity_profile(
            pumpswap_workers=args.pumpswap_workers,
            pump_prepare_workers=args.pump_prepare_workers,
            pumpswap_prepare_submitters=args.pumpswap_prepare_submitters,
            pumpswap_prepare_executor_workers=args.pumpswap_prepare_executor_workers,
            default_io_workers=args.default_io_workers,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.hydration_batch_workers * args.hedge_endpoints > args.max_concurrent_resolutions:
        raise SystemExit(
            "hydration-batch-workers * hedge-endpoints must not exceed max-concurrent-resolutions"
        )

    print("Crypto Copy Trader — Unified Market Route-Only Research Smoke v49")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — systems scheduling stabilization only; "
        "no taker, signing, transaction submission or official decision freeze."
    )
    asyncio.run(
        run_smoke_v49(
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
