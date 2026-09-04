from __future__ import annotations

import argparse
import asyncio

import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v24 as v24
from src import database


async def run_smoke_v26(**kwargs):
    """Run v24 with no-op radar results removed from the stateful dependency graph.

    v24 proved that both Pump and PumpSwap causal read/detect preparation can keep up,
    while stateful finalization still accumulated large queues. v26 preserves the same
    detector, replay, reservation, SQLite IMMEDIATE admission, Pump ingress classification,
    PumpSwap per-asset ticketing and one shared trigger-commit executor, but only actual
    trigger-bearing work remains on the stateful path.

    Pump no-trigger results complete immediately after ingress-ordered classification;
    trigger-bearing Pump work is queued FIFO to the shared commit executor so a slow write
    cannot block later no-trigger decisions. PumpSwap no-trigger and no-new-evidence
    reservations are marked as causal no-ops in the scheduler: their tickets are remembered
    only until earlier stateful predecessors complete, then skipped automatically. Later
    stateful work can never overtake an earlier stateful predecessor.
    """

    kwargs = dict(kwargs)
    kwargs["stateful_only_finalize"] = True
    return await v24.run_smoke_v24(**kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v26 stateful-only radar finalization"
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
    print("Crypto Copy Trader — Unified Market Latency Smoke v26 Stateful-Only Finalization")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"pump_writer=ordered_microbatch batch_size={args.pump_batch_size} "
        f"batch_max_wait_ms={args.pump_batch_max_wait_ms} "
        f"pump_prepare_workers={args.pump_prepare_workers} pump_trigger_commit_workers=1 "
        f"pumpswap_workers={args.pumpswap_workers} pumpswap_sqlite_writer_threads=1 "
        f"pumpswap_writer_loop=thread_owned "
        f"pumpswap_writer_batch_size={args.pumpswap_writer_batch_size} "
        f"pumpswap_writer_batch_max_wait_ms={args.pumpswap_writer_batch_max_wait_ms} "
        f"pumpswap_prepare_submitters={args.pumpswap_prepare_submitters} "
        f"pumpswap_prepare_executor_workers={args.pumpswap_prepare_executor_workers} "
        f"market_radar_trigger_commit_executor_workers=1 "
        f"no_trigger_stateful_dependency=false "
        f"sqlite_transaction_mode=IMMEDIATE "
        f"sqlite_busy_timeout_ms={int(database._SQLITE_BUSY_TIMEOUT_SECONDS * 1000)} "
        f"concurrent_resolutions={args.max_concurrent_resolutions} event_loop_lag_probe_ms=20 "
        f"max_hydrations={args.max_hydrations} queue_size={args.queue_size} "
        f"sqlite_journal_mode={journal_mode} sqlite_synchronous={synchronous}"
    )
    print(
        "v26 preserves every state-mutating ordering rule from v24. Only proven no-op detector "
        "results are removed from the serialized dependency graph; actual Pump/PumpSwap trigger "
        "commits still share one off-loop commit executor."
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
        asyncio.run(run_smoke_v26(**kwargs))
    finally:
        print("\nV26 STATEFUL-ONLY FINALIZATION / NO-OP ELISION DIAGNOSTIC")
        print(
            "pump_no_trigger=inline_after_ingress_classification "
            "pump_trigger=ordered_commit_queue "
            "pumpswap_no_trigger=causal_ticket_elision "
            "pumpswap_trigger=per_asset_fifo "
            "shared_trigger_commit_executor=1"
        )
        print(
            "v26 removes only proven no-op results from stateful ordering; state-mutating trigger "
            "commits retain Pump ingress ordering, PumpSwap per-asset FIFO and shared SQLite commit "
            "serialization."
        )
        v19._print_replay_telemetry(args.run_key)


if __name__ == "__main__":
    main()
