from __future__ import annotations

import argparse
import asyncio

import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v24 as v24
from src import database


def _prepared_has_trigger(prepared) -> bool:
    return any(token.trigger is not None for token in prepared.tokens)


async def run_smoke_v25(**kwargs):
    """Run v24 while sending only state-mutating radar work to the serial executor.

    v24 proved that Pump and PumpSwap causal read/detect preparation can keep up off-loop,
    while the shared one-thread finalize executor still accumulated thousands of jobs.
    Most prepared notifications contain no detector trigger at all, so their finalize path
    performs no trigger/episode SQLite write. v25 lets those no-trigger notifications cross
    the existing Pump ingress / PumpSwap per-asset FIFO boundary and finalize inline; only
    prepared notifications containing at least one trigger use the shared serial executor.
    Cross-source trigger persistence remains globally serialized and all detector, replay,
    reservation, as_of and SQLite writer-admission semantics stay frozen.
    """

    original_run_sync_stage = v19._run_sync_stage
    stateful_finalizers = {
        v19.finalize_prepared_pump_radar_v5,
        v19.finalize_prepared_pumpswap_radar_v5,
    }

    async def commit_only_run_sync_stage(
        function,
        /,
        *args,
        executor=None,
        **stage_kwargs,
    ):
        if (
            executor is not None
            and function in stateful_finalizers
            and args
            and not _prepared_has_trigger(args[0])
        ):
            return function(*args, **stage_kwargs)
        return await original_run_sync_stage(
            function,
            *args,
            executor=executor,
            **stage_kwargs,
        )

    v19._run_sync_stage = commit_only_run_sync_stage
    try:
        return await v24.run_smoke_v24(**kwargs)
    finally:
        v19._run_sync_stage = original_run_sync_stage
        print("\nV25 TRIGGER-COMMIT-ONLY SERIAL EXECUTOR DIAGNOSTIC")
        print(
            "no_trigger_finalize=inline trigger_finalize=shared_serial_executor "
            "pump_ingress_order=preserved pumpswap_asset_fifo=preserved "
            "cross_source_trigger_serialization=preserved"
        )
        print(
            "v25 changes finalize dispatch only relative to v24: prepared notifications without "
            "a detector trigger bypass the serial executor because they perform no episode/trigger "
            "write; all state-mutating finalizations keep the same one-thread commit executor."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v25 trigger-commit-only serial executor"
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1500)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-batch-size", type=int, default=32)
    parser.add_argument("--pump-batch-max-wait-ms", type=int, default=25)
    parser.add_argument("--pump-prepare-workers", type=int, default=4)
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
    if args.pump_prepare_workers <= 0:
        parser.error("pump-prepare-workers must be positive")
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
    print("Crypto Copy Trader — Unified Market Latency Smoke v25 Trigger Commit Only")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"pump_writer=ordered_microbatch batch_size={args.pump_batch_size} "
        f"batch_max_wait_ms={args.pump_batch_max_wait_ms} "
        f"pump_prepare_workers={args.pump_prepare_workers} pump_finalize_workers=1 "
        f"pumpswap_workers={args.pumpswap_workers} pumpswap_sqlite_writer_threads=1 "
        f"pumpswap_writer_loop=thread_owned "
        f"pumpswap_writer_batch_size={args.pumpswap_writer_batch_size} "
        f"pumpswap_writer_batch_max_wait_ms={args.pumpswap_writer_batch_max_wait_ms} "
        f"pumpswap_prepare_submitters={args.pumpswap_prepare_submitters} "
        f"pumpswap_prepare_executor_workers={args.pumpswap_prepare_executor_workers} "
        f"market_radar_trigger_commit_executor_workers=1 "
        f"no_trigger_finalize=inline "
        f"sqlite_transaction_mode=IMMEDIATE "
        f"sqlite_busy_timeout_ms={int(database._SQLITE_BUSY_TIMEOUT_SECONDS * 1000)} "
        f"concurrent_resolutions={args.max_concurrent_resolutions} event_loop_lag_probe_ms=20 "
        f"max_hydrations={args.max_hydrations} queue_size={args.queue_size} "
        f"sqlite_journal_mode={journal_mode} sqlite_synchronous={synchronous}"
    )
    print(
        "v25 keeps v24 Pump prepare/reorder and PumpSwap prepare/FIFO behavior. Only prepared "
        "notifications that contain an actual detector trigger enter the shared serial commit "
        "executor; no-trigger finalization is read-only/object construction and runs inline."
    )

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
    )
    try:
        asyncio.run(run_smoke_v25(**kwargs))
    finally:
        v19._print_replay_telemetry(args.run_key)


if __name__ == "__main__":
    main()
