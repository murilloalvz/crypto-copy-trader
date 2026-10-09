from __future__ import annotations

import argparse
import asyncio

import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v22 as v22
from src import database


async def run_smoke_v23(**kwargs):
    """Run v22 after switching shared SQLite connections to IMMEDIATE writer admission.

    v22 proved that offloading the sequential Pump radar and PumpSwap finalize stages
    materially reduces asyncio event-loop lag, but two live runs then failed with
    ``database is locked`` on different writers. v23 keeps the v22 scheduling, detector,
    replay, reservation and FIFO semantics unchanged and relies on the shared database
    connection policy to reserve the SQLite writer with an IMMEDIATE transaction at the
    first DML. Pure reads remain transaction-free/concurrent in WAL mode. A bounded busy
    timeout lets short writer contention become measured latency instead of a premature
    traceback; persistent contention still fails loudly.
    """

    try:
        return await v22.run_smoke_v22(**kwargs)
    finally:
        print("\nV23 SQLITE IMMEDIATE WRITER ADMISSION DIAGNOSTIC")
        print(
            "sqlite_transaction_mode=IMMEDIATE "
            f"sqlite_busy_timeout_ms={int(database._SQLITE_BUSY_TIMEOUT_SECONDS * 1000)} "
            "wal_reads_remain_concurrent=true"
        )
        print(
            "v23 changes SQLite writer admission only relative to v22: detector/provider/replay/"
            "as_of/reservation/FIFO rules and all worker counts remain frozen."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v23 SQLite IMMEDIATE writer admission"
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

    if not 1 <= args.duration_seconds <= v19.MAX_SMOKE_SECONDS:
        parser.error(f"duration-seconds must be between 1 and {v19.MAX_SMOKE_SECONDS}")
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

    journal_mode, synchronous = v19._enable_wal_mode()
    print("Crypto Copy Trader — Unified Market Latency Smoke v23 SQLite Writer Admission")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"pump_writer=ordered_microbatch batch_size={args.pump_batch_size} "
        f"batch_max_wait_ms={args.pump_batch_max_wait_ms} "
        f"pumpswap_workers={args.pumpswap_workers} pumpswap_sqlite_writer_threads=1 "
        f"pumpswap_writer_loop=thread_owned "
        f"pumpswap_writer_batch_size={args.pumpswap_writer_batch_size} "
        f"pumpswap_writer_batch_max_wait_ms={args.pumpswap_writer_batch_max_wait_ms} "
        f"pumpswap_prepare_submitters={args.pumpswap_prepare_submitters} "
        f"pumpswap_prepare_executor_workers={args.pumpswap_prepare_executor_workers} "
        f"pumpswap_reservation_watermark=post_normalization_pre_writer_result "
        f"pumpswap_reservation_replay_index=preloaded_once "
        f"market_radar_sync_executor_workers=1 pumpswap_finalize_workers=1 "
        f"concurrent_resolutions={args.max_concurrent_resolutions} event_loop_lag_probe_ms=20 "
        f"sqlite_transaction_mode=IMMEDIATE "
        f"sqlite_busy_timeout_ms={int(database._SQLITE_BUSY_TIMEOUT_SECONDS * 1000)} "
        f"max_hydrations={args.max_hydrations} queue_size={args.queue_size} "
        f"sqlite_journal_mode={journal_mode} sqlite_synchronous={synchronous}"
    )
    print(
        "v23 keeps all v22 detector/provider/replay/as_of/reservation/FIFO and scheduling rules "
        "frozen; only shared SQLite writer admission changes from DEFERRED to IMMEDIATE."
    )

    kwargs = dict(
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
    try:
        asyncio.run(run_smoke_v23(**kwargs))
    finally:
        v19._print_replay_telemetry(args.run_key)


if __name__ == "__main__":
    main()
