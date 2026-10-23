import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor as RealThreadPoolExecutor

import unified_market_latency_smoke_v12 as v12
import unified_market_latency_smoke_v17 as v17
from unified_market_latency_smoke_v13 import _enable_wal_mode
from unified_market_latency_smoke_v5 import _print_replay_telemetry
from unified_market_throughput_smoke_v4 import MAX_SMOKE_SECONDS, _latency_summary_ms


async def run_smoke_v18(
    *,
    run_key: str,
    duration_seconds: int,
    commitment: str,
    max_hydrations: int,
    rpc_timeout_seconds: int,
    pump_batch_size: int,
    pump_batch_max_wait_ms: int,
    pumpswap_workers: int,
    pumpswap_prepare_submitters: int,
    pumpswap_prepare_executor_workers: int,
    pumpswap_writer_batch_size: int,
    pumpswap_writer_batch_max_wait_ms: int,
    max_concurrent_resolutions: int,
    queue_size: int,
) -> v17.ThreadedWriterDiagnostics:
    """Run v17 with more async prepare submitters than dedicated prepare threads.

    v17 proved the thread-owned writer is healthy, while prepare throughput remains
    limited by coroutine resumption latency. v18 changes only prepare scheduling:
    many lightweight async submitters keep a smaller dedicated executor saturated.
    SQLite read concurrency therefore stays bounded by
    ``pumpswap_prepare_executor_workers`` even though more notifications may wait on
    executor futures concurrently.
    """

    if pumpswap_prepare_submitters <= 0:
        raise ValueError("pumpswap_prepare_submitters must be positive")
    if pumpswap_prepare_executor_workers <= 0:
        raise ValueError("pumpswap_prepare_executor_workers must be positive")

    original_executor_factory = v12.ThreadPoolExecutor

    def bounded_prepare_executor(*args, **kwargs):
        thread_name_prefix = kwargs.get("thread_name_prefix", "")
        if thread_name_prefix == "pumpswap-prepare":
            return RealThreadPoolExecutor(
                max_workers=pumpswap_prepare_executor_workers,
                thread_name_prefix=thread_name_prefix,
            )
        return original_executor_factory(*args, **kwargs)

    v12.ThreadPoolExecutor = bounded_prepare_executor
    try:
        return await v17.run_smoke_v17(
            run_key=run_key,
            duration_seconds=duration_seconds,
            commitment=commitment,
            max_hydrations=max_hydrations,
            rpc_timeout_seconds=rpc_timeout_seconds,
            pump_batch_size=pump_batch_size,
            pump_batch_max_wait_ms=pump_batch_max_wait_ms,
            pumpswap_workers=pumpswap_workers,
            # v11 uses this value for the number of async prepare loops. v12's
            # executor factory above independently caps actual prepare threads.
            pumpswap_radar_workers=pumpswap_prepare_submitters,
            pumpswap_writer_batch_size=pumpswap_writer_batch_size,
            pumpswap_writer_batch_max_wait_ms=pumpswap_writer_batch_max_wait_ms,
            max_concurrent_resolutions=max_concurrent_resolutions,
            queue_size=queue_size,
        )
    finally:
        v12.ThreadPoolExecutor = original_executor_factory


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v18 decoupled PumpSwap prepare submitters"
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1500)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-batch-size", type=int, default=32)
    parser.add_argument("--pump-batch-max-wait-ms", type=int, default=25)
    parser.add_argument("--pumpswap-workers", type=int, default=64)
    parser.add_argument("--pumpswap-prepare-submitters", type=int, default=48)
    parser.add_argument("--pumpswap-prepare-executor-workers", type=int, default=12)
    parser.add_argument("--pumpswap-writer-batch-size", type=int, default=32)
    parser.add_argument("--pumpswap-writer-batch-max-wait-ms", type=int, default=10)
    parser.add_argument("--max-concurrent-resolutions", type=int, default=18)
    parser.add_argument("--queue-size", type=int, default=5000)
    args = parser.parse_args()

    if not 1 <= args.duration_seconds <= MAX_SMOKE_SECONDS:
        parser.error(f"duration-seconds must be between 1 and {MAX_SMOKE_SECONDS}")
    if args.pump_batch_size <= 1:
        parser.error("pump-batch-size must be greater than 1")
    if args.pump_batch_max_wait_ms < 0:
        parser.error("pump-batch-max-wait-ms cannot be negative")
    if args.pumpswap_writer_batch_size <= 1:
        parser.error("pumpswap-writer-batch-size must be greater than 1")
    if args.pumpswap_writer_batch_max_wait_ms < 0:
        parser.error("pumpswap-writer-batch-max-wait-ms cannot be negative")
    for name in (
        "max_hydrations",
        "rpc_timeout_seconds",
        "pumpswap_workers",
        "pumpswap_prepare_submitters",
        "pumpswap_prepare_executor_workers",
        "max_concurrent_resolutions",
        "queue_size",
    ):
        if getattr(args, name) <= 0:
            parser.error(f"{name.replace('_', '-')} must be positive")

    journal_mode, synchronous = _enable_wal_mode()

    print("Crypto Copy Trader — Unified Market Latency Smoke v18 Decoupled Prepare Submitters")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"pump_writer=ordered_microbatch batch_size={args.pump_batch_size} "
        f"batch_max_wait_ms={args.pump_batch_max_wait_ms} "
        f"pumpswap_workers={args.pumpswap_workers} "
        f"pumpswap_sqlite_writer_threads=1 pumpswap_writer_loop=thread_owned "
        f"pumpswap_writer_batch_size={args.pumpswap_writer_batch_size} "
        f"pumpswap_writer_batch_max_wait_ms={args.pumpswap_writer_batch_max_wait_ms} "
        f"pumpswap_prepare_submitters={args.pumpswap_prepare_submitters} "
        f"pumpswap_prepare_executor_workers={args.pumpswap_prepare_executor_workers} "
        f"pumpswap_finalize_workers=1 concurrent_resolutions={args.max_concurrent_resolutions} "
        f"max_hydrations={args.max_hydrations} queue_size={args.queue_size} "
        f"sqlite_journal_mode={journal_mode} sqlite_synchronous={synchronous}"
    )
    print(
        "v18 keeps v17's thread-owned WAL writer and all scientific semantics. Only prepare "
        "scheduling changes: 48 async submitters can keep a 12-thread dedicated prepare executor "
        "busy despite event-loop resumption delay; SQLite read concurrency remains capped at 12."
    )

    try:
        diagnostics = asyncio.run(
            run_smoke_v18(
                run_key=args.run_key,
                duration_seconds=args.duration_seconds,
                commitment=args.commitment,
                max_hydrations=args.max_hydrations,
                rpc_timeout_seconds=args.rpc_timeout_seconds,
                pump_batch_size=args.pump_batch_size,
                pump_batch_max_wait_ms=args.pump_batch_max_wait_ms,
                pumpswap_workers=args.pumpswap_workers,
                pumpswap_prepare_submitters=args.pumpswap_prepare_submitters,
                pumpswap_prepare_executor_workers=args.pumpswap_prepare_executor_workers,
                pumpswap_writer_batch_size=args.pumpswap_writer_batch_size,
                pumpswap_writer_batch_max_wait_ms=args.pumpswap_writer_batch_max_wait_ms,
                max_concurrent_resolutions=args.max_concurrent_resolutions,
                queue_size=args.queue_size,
            )
        )

        print("\nV18 DECOUPLED PREPARE / THREAD-OWNED WRITER DIAGNOSTIC")
        print(
            f"prepare_submitters={args.pumpswap_prepare_submitters} "
            f"prepare_executor_workers={args.pumpswap_prepare_executor_workers} "
            f"persistence_calls={len(diagnostics.writer_result_wait_seconds)} "
            f"writer_threads=1 writer_batches={len(diagnostics.batch_sizes)} "
            f"writer_queue_at_deadline={diagnostics.final_writer_queue_size}"
        )
        print(
            "pumpswap_writer_queue_wait_ms "
            f"{_latency_summary_ms(diagnostics.writer_queue_wait_seconds)}"
        )
        print(
            "pumpswap_writer_result_wait_ms "
            f"{_latency_summary_ms(diagnostics.writer_result_wait_seconds)}"
        )
        print(
            "pumpswap_writer_batch_service_ms "
            f"{_latency_summary_ms(diagnostics.batch_service_seconds)}"
        )
        avg_batch = (
            sum(diagnostics.batch_sizes) / len(diagnostics.batch_sizes)
            if diagnostics.batch_sizes
            else 0.0
        )
        max_batch = max(diagnostics.batch_sizes) if diagnostics.batch_sizes else 0
        print(
            f"pumpswap_writer_microbatch batches={len(diagnostics.batch_sizes)} "
            f"avg_size={avg_batch:.2f} max_size={max_batch} "
            f"configured_size={args.pumpswap_writer_batch_size} "
            f"max_wait_ms={args.pumpswap_writer_batch_max_wait_ms}"
        )
    finally:
        _print_replay_telemetry(args.run_key)


if __name__ == "__main__":
    main()
