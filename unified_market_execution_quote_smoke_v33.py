from __future__ import annotations

import argparse
import asyncio

from src.pumpswap_hedged_batched_resolver_v33 import HedgedBatchedBoundedResolverV33
import unified_market_execution_quote_smoke_v31 as v31
import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v30 as v30


async def run_smoke_v33(
    *,
    hydration_batch_size: int,
    hydration_batch_max_wait_ms: int,
    hedge_endpoints: int,
    **kwargs,
) -> None:
    if hydration_batch_size <= 0:
        raise ValueError("hydration_batch_size must be positive")
    if hydration_batch_max_wait_ms < 0:
        raise ValueError("hydration_batch_max_wait_ms cannot be negative")
    if hedge_endpoints <= 0:
        raise ValueError("hedge_endpoints must be positive")

    original_resolver = v19.BoundedConcurrentResolver

    class ConfiguredHedgedResolver(HedgedBatchedBoundedResolverV33):
        def __init__(self, *args, **resolver_kwargs):
            super().__init__(
                *args,
                hydration_batch_size=hydration_batch_size,
                hydration_batch_max_wait_ms=hydration_batch_max_wait_ms,
                hedge_endpoints=hedge_endpoints,
                **resolver_kwargs,
            )

    HedgedBatchedBoundedResolverV33.last_instance = None
    v19.BoundedConcurrentResolver = ConfiguredHedgedResolver
    try:
        await v31.run_smoke_v31(**kwargs)
    finally:
        v19.BoundedConcurrentResolver = original_resolver

    resolver = HedgedBatchedBoundedResolverV33.last_instance
    print("\nV33 HEDGED BATCHED PUMPSWAP HYDRATION DIAGNOSTIC")
    if resolver is None:
        print("resolver_instance=missing")
    else:
        print(
            f"pool_hydrations={resolver.network_hydration_calls} "
            f"successful_batches={resolver.network_batch_calls} "
            f"avg_batch_size={resolver.average_network_batch_size:.2f} "
            f"max_batch_size={resolver.max_network_batch_size} "
            f"hedged_batch_calls={resolver.hedged_batch_calls} "
            f"endpoint_requests={resolver.hedged_endpoint_requests} "
            f"all_hedges_failed={resolver.hedged_all_failed} "
            f"hedge_endpoints={resolver.hedge_endpoints}"
        )
        print(
            f"hydration_successes={resolver.hydration_successes} "
            f"hydration_failures={resolver.hydration_failures} "
            f"budget_skips={resolver.hydration_budget_skips} "
            f"negative_cache_skips={resolver.negative_cache_skips} "
            f"singleflight_waits={resolver.singleflight_waits} "
            f"cache_hits={resolver.cache_hits}"
        )
    print(
        "v33 keeps v32 batching and all v30 causal/FIFO rules, but removes sequential "
        "per-endpoint retries from the latency-critical unknown-pool path. Up to the configured "
        "number of RPC endpoints receive one batch request each in parallel; first valid response wins."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market v33 Jupiter quote smoke with hedged batched PumpSwap hydration"
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

    print("Crypto Copy Trader — Unified Market Execution Quote Smoke v33")
    print("Mode: PAPER / RESEARCH / READ ONLY — hedged pool identity reads + Jupiter order assembly only; no signing/execute.")
    asyncio.run(
        run_smoke_v33(
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
