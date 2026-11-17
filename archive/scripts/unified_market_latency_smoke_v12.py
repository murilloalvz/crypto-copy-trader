import argparse
import asyncio
import contextvars
from concurrent.futures import ThreadPoolExecutor
import functools

from src.pumpswap_radar_bridge_v5 import prepare_persisted_pumpswap_notification_for_radar_v5
from unified_market_latency_smoke_v5 import _print_replay_telemetry
from unified_market_latency_smoke_v11 import run_smoke_v11
from unified_market_throughput_smoke_v4 import MAX_SMOKE_SECONDS


async def run_smoke_v12(
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
    """Run v11 semantics with a dedicated executor for PumpSwap prepare work.

    v11b showed that adding prepare coroutines did not scale because the measured
    ``await asyncio.to_thread(...)`` time was much larger than the bridge's internal
    DB/detector time. v12 changes only executor isolation/capacity: Pump, persistence,
    detector, causal clocks, reservations, trigger keys, replay and episode semantics
    stay identical to v11.
    """

    original_to_thread = asyncio.to_thread
    prepare_executor = ThreadPoolExecutor(
        max_workers=pumpswap_radar_workers,
        thread_name_prefix="pumpswap-prepare",
    )

    async def routed_to_thread(func, /, *args, **kwargs):
        if func is prepare_persisted_pumpswap_notification_for_radar_v5:
            loop = asyncio.get_running_loop()
            context = contextvars.copy_context()
            call = functools.partial(context.run, func, *args, **kwargs)
            return await loop.run_in_executor(prepare_executor, call)
        return await original_to_thread(func, *args, **kwargs)

    asyncio.to_thread = routed_to_thread
    try:
        await run_smoke_v11(
            run_key=run_key,
            duration_seconds=duration_seconds,
            commitment=commitment,
            max_hydrations=max_hydrations,
            rpc_timeout_seconds=rpc_timeout_seconds,
            pump_batch_size=pump_batch_size,
            pump_batch_max_wait_ms=pump_batch_max_wait_ms,
            pumpswap_workers=pumpswap_workers,
            pumpswap_radar_workers=pumpswap_radar_workers,
            max_concurrent_resolutions=max_concurrent_resolutions,
            queue_size=queue_size,
        )
    finally:
        asyncio.to_thread = original_to_thread
        prepare_executor.shutdown(wait=True, cancel_futures=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v12 dedicated PumpSwap prepare executor"
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1500)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-batch-size", type=int, default=32)
    parser.add_argument("--pump-batch-max-wait-ms", type=int, default=25)
    parser.add_argument("--pumpswap-workers", type=int, default=24)
    parser.add_argument("--pumpswap-radar-workers", type=int, default=12)
    parser.add_argument("--max-concurrent-resolutions", type=int, default=18)
    parser.add_argument("--queue-size", type=int, default=5000)
    args = parser.parse_args()

    if not 1 <= args.duration_seconds <= MAX_SMOKE_SECONDS:
        parser.error(f"duration-seconds must be between 1 and {MAX_SMOKE_SECONDS}")
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
            parser.error(f"{name.replace('_', '-')} must be positive")

    print("Crypto Copy Trader — Unified Market Latency Smoke v12 Dedicated Prepare Executor")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"pump_writer=ordered_microbatch batch_size={args.pump_batch_size} "
        f"batch_max_wait_ms={args.pump_batch_max_wait_ms} "
        f"pumpswap_workers={args.pumpswap_workers} "
        f"pumpswap_prepare_workers={args.pumpswap_radar_workers} "
        f"pumpswap_prepare_executor_workers={args.pumpswap_radar_workers} "
        f"pumpswap_finalize_workers=1 concurrent_resolutions={args.max_concurrent_resolutions} "
        f"max_hydrations={args.max_hydrations} queue_size={args.queue_size}"
    )
    print(
        "v12 isolates PumpSwap prepare work in a dedicated ThreadPoolExecutor. "
        "v11 prepare/finalize semantics and all scientific gates are unchanged."
    )

    try:
        asyncio.run(
            run_smoke_v12(
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
