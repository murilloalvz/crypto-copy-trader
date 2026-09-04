from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor

import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v29 as v29


# v29 live measurements at ~75 PumpSwap notifications/s showed that the authoritative
# writer was no longer the limiter (writer batch service p95 ~110ms), while the fixed
# orchestration/prepare pools were mathematically at or below arrival capacity.
MIN_PUMPSWAP_WORKERS = 128
MIN_PUMP_PREPARE_WORKERS = 12
MIN_PUMPSWAP_PREPARE_SUBMITTERS = 64
MIN_PUMPSWAP_PREPARE_EXECUTOR_WORKERS = 32
MIN_DEFAULT_IO_WORKERS = 32


def validate_capacity_profile(
    *,
    pumpswap_workers: int,
    pump_prepare_workers: int,
    pumpswap_prepare_submitters: int,
    pumpswap_prepare_executor_workers: int,
    default_io_workers: int,
) -> None:
    minimums = {
        "pumpswap_workers": (pumpswap_workers, MIN_PUMPSWAP_WORKERS),
        "pump_prepare_workers": (pump_prepare_workers, MIN_PUMP_PREPARE_WORKERS),
        "pumpswap_prepare_submitters": (
            pumpswap_prepare_submitters,
            MIN_PUMPSWAP_PREPARE_SUBMITTERS,
        ),
        "pumpswap_prepare_executor_workers": (
            pumpswap_prepare_executor_workers,
            MIN_PUMPSWAP_PREPARE_EXECUTOR_WORKERS,
        ),
        "default_io_workers": (default_io_workers, MIN_DEFAULT_IO_WORKERS),
    }
    for name, (actual, minimum) in minimums.items():
        if int(actual) < int(minimum):
            raise ValueError(f"{name} must be >= {minimum} for the v30 capacity profile")

    # Submitter coroutines are only useful when they can keep the explicit prepare
    # executor fed. Fail closed on an accidentally inverted profile.
    if pumpswap_prepare_submitters < pumpswap_prepare_executor_workers:
        raise ValueError(
            "pumpswap_prepare_submitters must be >= pumpswap_prepare_executor_workers"
        )


async def run_smoke_v30(*, default_io_workers: int, **kwargs):
    """Run v29 with measured orchestration capacity instead of changing market semantics.

    v29 removed the SQLite statement-count bottleneck and persisted 100% of notifications, but its
    live profile still had two artificial queue ceilings:

    * 64 PumpSwap orchestration workers had p95 service capacity almost exactly equal to measured
      arrival rate, so burst traffic queued before normalization;
    * 12 PumpSwap prepare threads had even median capacity below measured arrival rate, while four
      Pump prepare threads were tail-underprovisioned;
    * RPC hydration uses ``asyncio.to_thread``. On a small-core machine the loop default executor
      can expose fewer threads than the separately bounded resolution semaphore, causing network
      waits to create ingress-sequence holes even though resolver concurrency itself is capped.

    v30 changes only capacity/scheduling. Network hydration remains bounded by the existing
    ``max_concurrent_resolutions`` argument, PumpSwap persistence still uses one thread-owned
    microbatch writer, SQLite writer admission remains prioritized, and all detector/replay/as_of/
    reservation/FIFO/episode rules are inherited unchanged from v29.
    """

    validate_capacity_profile(
        pumpswap_workers=kwargs["pumpswap_workers"],
        pump_prepare_workers=kwargs["pump_prepare_workers"],
        pumpswap_prepare_submitters=kwargs["pumpswap_prepare_submitters"],
        pumpswap_prepare_executor_workers=kwargs["pumpswap_prepare_executor_workers"],
        default_io_workers=default_io_workers,
    )

    loop = asyncio.get_running_loop()
    # ``asyncio.run`` owns shutdown of the loop default executor. Installing it here keeps
    # blocking RPC hydration/Pump persistence off the tiny platform default pool without
    # increasing the independently enforced network-resolution semaphore.
    loop.set_default_executor(
        ThreadPoolExecutor(
            max_workers=default_io_workers,
            thread_name_prefix="unified-market-io-v30",
        )
    )

    try:
        return await v29.run_smoke_v29(**kwargs)
    finally:
        print("\nV30 MEASURED POST-PERSISTENCE CAPACITY DIAGNOSTIC")
        print(
            f"pumpswap_workers={kwargs['pumpswap_workers']} "
            f"pump_prepare_workers={kwargs['pump_prepare_workers']} "
            f"pumpswap_prepare_submitters={kwargs['pumpswap_prepare_submitters']} "
            f"pumpswap_prepare_executor_workers={kwargs['pumpswap_prepare_executor_workers']} "
            f"default_io_workers={default_io_workers} "
            f"max_concurrent_resolutions={kwargs['max_concurrent_resolutions']}"
        )
        print(
            "v30 changes scheduling capacity only relative to v29. The RPC semaphore and SQLite "
            "single-writer architecture remain bounded; detector/provider/as_of/replay/FIFO/"
            "episode semantics are unchanged."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v30 measured post-persistence capacity"
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1500)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-batch-size", type=int, default=32)
    parser.add_argument("--pump-batch-max-wait-ms", type=int, default=25)
    parser.add_argument("--pump-prepare-workers", type=int, default=MIN_PUMP_PREPARE_WORKERS)
    parser.add_argument("--pumpswap-workers", type=int, default=MIN_PUMPSWAP_WORKERS)
    parser.add_argument(
        "--pumpswap-prepare-submitters",
        type=int,
        default=MIN_PUMPSWAP_PREPARE_SUBMITTERS,
    )
    parser.add_argument(
        "--pumpswap-prepare-executor-workers",
        type=int,
        default=MIN_PUMPSWAP_PREPARE_EXECUTOR_WORKERS,
    )
    parser.add_argument("--pumpswap-writer-batch-size", type=int, default=32)
    parser.add_argument("--pumpswap-writer-batch-max-wait-ms", type=int, default=10)
    parser.add_argument("--max-concurrent-resolutions", type=int, default=18)
    parser.add_argument("--queue-size", type=int, default=5000)
    parser.add_argument("--continuation-batch-size", type=int, default=32)
    parser.add_argument("--continuation-batch-max-wait-ms", type=int, default=5)
    parser.add_argument("--default-io-workers", type=int, default=MIN_DEFAULT_IO_WORKERS)
    args = parser.parse_args()

    if not 1 <= args.duration_seconds <= v19.MAX_SMOKE_SECONDS:
        parser.error(f"duration-seconds must be between 1 and {v19.MAX_SMOKE_SECONDS}")
    for name in (
        "pump_batch_size",
        "pump_prepare_workers",
        "pumpswap_workers",
        "pumpswap_prepare_submitters",
        "pumpswap_prepare_executor_workers",
        "pumpswap_writer_batch_size",
        "max_concurrent_resolutions",
        "queue_size",
        "continuation_batch_size",
        "max_hydrations",
        "rpc_timeout_seconds",
        "default_io_workers",
    ):
        if getattr(args, name) <= 0:
            parser.error(f"{name.replace('_', '-')} must be positive")
    if args.pump_batch_max_wait_ms < 0:
        parser.error("pump-batch-max-wait-ms cannot be negative")
    if args.pumpswap_writer_batch_max_wait_ms < 0:
        parser.error("pumpswap-writer-batch-max-wait-ms cannot be negative")
    if args.continuation_batch_max_wait_ms < 0:
        parser.error("continuation-batch-max-wait-ms cannot be negative")

    try:
        validate_capacity_profile(
            pumpswap_workers=args.pumpswap_workers,
            pump_prepare_workers=args.pump_prepare_workers,
            pumpswap_prepare_submitters=args.pumpswap_prepare_submitters,
            pumpswap_prepare_executor_workers=args.pumpswap_prepare_executor_workers,
            default_io_workers=args.default_io_workers,
        )
    except ValueError as exc:
        parser.error(str(exc))

    print("Crypto Copy Trader — Unified Market Latency Smoke v30 Measured Capacity")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")

    kwargs = dict(
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
    asyncio.run(run_smoke_v30(default_io_workers=args.default_io_workers, **kwargs))


if __name__ == "__main__":
    main()
