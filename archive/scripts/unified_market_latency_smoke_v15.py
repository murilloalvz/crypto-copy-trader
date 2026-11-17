import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import threading

import unified_market_latency_smoke_v11 as v11
from src.pumpswap_normalized_persistence_v2 import (
    PumpSwapPersistenceV2Telemetry,
    persist_pumpswap_notification_normalized_v2,
)
from unified_market_latency_smoke_v5 import _print_replay_telemetry
from unified_market_latency_smoke_v12 import run_smoke_v12
from unified_market_latency_smoke_v13 import _enable_wal_mode
from unified_market_throughput_smoke_v4 import MAX_SMOKE_SECONDS, _latency_summary_ms


@dataclass
class PersistenceOffloadDiagnostics:
    resolver_and_normalize_seconds: list[float] = field(default_factory=list)
    writer_queue_wait_seconds: list[float] = field(default_factory=list)
    writer_service_seconds: list[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, item: PumpSwapPersistenceV2Telemetry) -> None:
        with self._lock:
            self.resolver_and_normalize_seconds.append(item.resolver_and_normalize_seconds)
            self.writer_queue_wait_seconds.append(item.writer_queue_wait_seconds)
            self.writer_service_seconds.append(item.writer_service_seconds)


async def run_smoke_v15(
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
) -> PersistenceOffloadDiagnostics:
    """Keep v13/WAL + v12 prepare isolation and offload SQLite writes from the event loop.

    v14 proved the prepare function itself is cheap (inner p95 ~86ms) while its outer await
    remained ~1.37s. The remaining delay is therefore outside the prepare thread. PumpSwap
    persistence still performs synchronous SQLite writes directly in 24 asyncio workers, which
    can monopolize the event loop during bursts. v15 keeps async resolver concurrency but routes
    canonical observation writes/readback through one explicit SQLite writer thread.
    """

    diagnostics = PersistenceOffloadDiagnostics()
    writer_executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="pumpswap-sqlite-writer",
    )

    async def offloaded_persist(notification, *, acquisition_run_key: str, resolver):
        return await persist_pumpswap_notification_normalized_v2(
            notification,
            acquisition_run_key=acquisition_run_key,
            resolver=resolver,
            db_executor=writer_executor,
            telemetry_sink=diagnostics.record,
        )

    original_persist = v11.persist_pumpswap_notification_normalized
    v11.persist_pumpswap_notification_normalized = offloaded_persist
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
        writer_executor.shutdown(wait=True, cancel_futures=True)

    return diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v15 dedicated PumpSwap SQLite writer"
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

    journal_mode, synchronous = _enable_wal_mode()

    print("Crypto Copy Trader — Unified Market Latency Smoke v15 Dedicated SQLite Writer")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"pump_writer=ordered_microbatch batch_size={args.pump_batch_size} "
        f"batch_max_wait_ms={args.pump_batch_max_wait_ms} "
        f"pumpswap_workers={args.pumpswap_workers} "
        f"pumpswap_sqlite_writer_workers=1 "
        f"pumpswap_prepare_workers={args.pumpswap_radar_workers} "
        f"pumpswap_prepare_executor_workers={args.pumpswap_radar_workers} "
        f"pumpswap_finalize_workers=1 concurrent_resolutions={args.max_concurrent_resolutions} "
        f"max_hydrations={args.max_hydrations} queue_size={args.queue_size} "
        f"sqlite_journal_mode={journal_mode} sqlite_synchronous={synchronous}"
    )
    print(
        "v15 preserves WAL, detector, causal clocks, replay, pool resolution, reservation FIFO "
        "and prepared-radar semantics. Only canonical PumpSwap SQLite observation writes/readback "
        "move off the asyncio event loop into one dedicated writer thread."
    )

    try:
        diagnostics = asyncio.run(
            run_smoke_v15(
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
        print("\nV15 PUMPSWAP SQLITE WRITER DIAGNOSTIC")
        print(f"persistence_calls={len(diagnostics.writer_service_seconds)} writer_workers=1")
        print(
            "pumpswap_resolver_normalize_ms "
            f"{_latency_summary_ms(diagnostics.resolver_and_normalize_seconds)}"
        )
        print(
            "pumpswap_writer_queue_wait_ms "
            f"{_latency_summary_ms(diagnostics.writer_queue_wait_seconds)}"
        )
        print(
            "pumpswap_writer_service_ms "
            f"{_latency_summary_ms(diagnostics.writer_service_seconds)}"
        )
    finally:
        _print_replay_telemetry(args.run_key)


if __name__ == "__main__":
    main()
