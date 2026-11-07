import argparse
import asyncio
from dataclasses import dataclass, field
import threading

import unified_market_latency_smoke_v11 as v11
from src.pumpswap_normalized_persistence_v3 import PumpSwapPersistenceV3Telemetry
from src.pumpswap_normalized_persistence_v4 import (
    PumpSwapSQLiteThreadedMicrobatchWriter,
    persist_pumpswap_notification_normalized_v4,
)
from unified_market_latency_smoke_v5 import _print_replay_telemetry
from unified_market_latency_smoke_v12 import run_smoke_v12
from unified_market_latency_smoke_v13 import _enable_wal_mode
from unified_market_throughput_smoke_v4 import MAX_SMOKE_SECONDS, _latency_summary_ms


@dataclass
class ThreadedWriterDiagnostics:
    resolver_and_normalize_seconds: list[float] = field(default_factory=list)
    writer_queue_wait_seconds: list[float] = field(default_factory=list)
    writer_result_wait_seconds: list[float] = field(default_factory=list)
    per_request_batch_service_seconds: list[float] = field(default_factory=list)
    per_request_batch_sizes: list[int] = field(default_factory=list)
    batch_sizes: list[int] = field(default_factory=list)
    batch_service_seconds: list[float] = field(default_factory=list)
    final_writer_queue_size: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, item: PumpSwapPersistenceV3Telemetry) -> None:
        with self._lock:
            self.resolver_and_normalize_seconds.append(item.resolver_and_normalize_seconds)
            self.writer_queue_wait_seconds.append(item.writer_queue_wait_seconds)
            self.writer_result_wait_seconds.append(item.writer_result_wait_seconds)
            self.per_request_batch_service_seconds.append(item.writer_batch_service_seconds)
            self.per_request_batch_sizes.append(item.writer_batch_size)


async def run_smoke_v17(
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
    pumpswap_writer_batch_size: int,
    pumpswap_writer_batch_max_wait_ms: int,
    max_concurrent_resolutions: int,
    queue_size: int,
) -> ThreadedWriterDiagnostics:
    """Keep v16 semantics while moving the entire PumpSwap writer loop off asyncio."""

    diagnostics = ThreadedWriterDiagnostics()
    writer = PumpSwapSQLiteThreadedMicrobatchWriter(
        batch_size=pumpswap_writer_batch_size,
        max_wait_ms=pumpswap_writer_batch_max_wait_ms,
        telemetry_sink=diagnostics.record,
    )

    async def threaded_persist(notification, *, acquisition_run_key: str, resolver):
        return await persist_pumpswap_notification_normalized_v4(
            notification,
            acquisition_run_key=acquisition_run_key,
            resolver=resolver,
            writer=writer,
        )

    original_persist = v11.persist_pumpswap_notification_normalized
    v11.persist_pumpswap_notification_normalized = threaded_persist
    try:
        await run_smoke_v12(
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
        v11.persist_pumpswap_notification_normalized = original_persist
        diagnostics.final_writer_queue_size = writer.queue_size
        await writer.close(cancel_pending=True)
        diagnostics.batch_sizes = list(writer.batch_sizes)
        diagnostics.batch_service_seconds = list(writer.batch_service_seconds)

    return diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v17 threaded PumpSwap SQLite writer"
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1500)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-batch-size", type=int, default=32)
    parser.add_argument("--pump-batch-max-wait-ms", type=int, default=25)
    parser.add_argument("--pumpswap-workers", type=int, default=64)
    parser.add_argument("--pumpswap-radar-workers", type=int, default=12)
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
        "pumpswap_radar_workers",
        "max_concurrent_resolutions",
        "queue_size",
    ):
        if getattr(args, name) <= 0:
            parser.error(f"{name.replace('_', '-')} must be positive")

    journal_mode, synchronous = _enable_wal_mode()

    print("Crypto Copy Trader — Unified Market Latency Smoke v17 Thread-Owned Writer")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"pump_writer=ordered_microbatch batch_size={args.pump_batch_size} "
        f"batch_max_wait_ms={args.pump_batch_max_wait_ms} "
        f"pumpswap_workers={args.pumpswap_workers} "
        f"pumpswap_sqlite_writer_threads=1 "
        f"pumpswap_writer_loop=thread_owned "
        f"pumpswap_writer_batch_size={args.pumpswap_writer_batch_size} "
        f"pumpswap_writer_batch_max_wait_ms={args.pumpswap_writer_batch_max_wait_ms} "
        f"pumpswap_prepare_workers={args.pumpswap_radar_workers} "
        f"pumpswap_prepare_executor_workers={args.pumpswap_radar_workers} "
        f"pumpswap_finalize_workers=1 concurrent_resolutions={args.max_concurrent_resolutions} "
        f"max_hydrations={args.max_hydrations} queue_size={args.queue_size} "
        f"sqlite_journal_mode={journal_mode} sqlite_synchronous={synchronous}"
    )
    print(
        "v17 keeps v16 persistence/replay semantics and moves batch collection plus SQLite "
        "execution onto one dedicated OS thread. The writer no longer needs asyncio scheduling "
        "between batches; detector, causal clocks, reservation FIFO and provider policy are unchanged."
    )

    try:
        diagnostics = asyncio.run(
            run_smoke_v17(
                run_key=args.run_key,
                duration_seconds=args.duration_seconds,
                commitment=args.commitment,
                max_hydrations=args.max_hydrations,
                rpc_timeout_seconds=args.rpc_timeout_seconds,
                pump_batch_size=args.pump_batch_size,
                pump_batch_max_wait_ms=args.pump_batch_max_wait_ms,
                pumpswap_workers=args.pumpswap_workers,
                pumpswap_radar_workers=args.pumpswap_radar_workers,
                pumpswap_writer_batch_size=args.pumpswap_writer_batch_size,
                pumpswap_writer_batch_max_wait_ms=args.pumpswap_writer_batch_max_wait_ms,
                max_concurrent_resolutions=args.max_concurrent_resolutions,
                queue_size=args.queue_size,
            )
        )

        print("\nV17 PUMPSWAP THREAD-OWNED WRITER DIAGNOSTIC")
        print(
            f"persistence_calls={len(diagnostics.writer_result_wait_seconds)} "
            f"writer_threads=1 writer_batches={len(diagnostics.batch_sizes)} "
            f"writer_queue_at_deadline={diagnostics.final_writer_queue_size}"
        )
        print(
            "pumpswap_resolver_normalize_ms "
            f"{_latency_summary_ms(diagnostics.resolver_and_normalize_seconds)}"
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
