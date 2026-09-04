from __future__ import annotations

import argparse
import asyncio

import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v28 as v28
import src.pumpswap_normalized_persistence_v4 as pumpswap_writer_module
from src.pumpswap_persistence_fastpath_v29 import (
    persist_prepared_batch_fast_v29,
    pumpswap_persistence_fastpath_snapshot,
    reset_pumpswap_persistence_fastpath_metrics,
)


async def run_smoke_v29(**kwargs):
    """Run v28 with an optimized authoritative PumpSwap persistence transaction.

    v28 proved that explicit writer admission removes lock races but cannot fix long PumpSwap
    transactions. v29 changes only the internal SQL shape of the PumpSwap microbatch writer:

    * new rows use INSERT OR IGNORE first;
    * replay/conflict SELECTs run only after a UNIQUE collision;
    * canonical affected tokens for transaction keys unique inside a microbatch share one readback;
    * repeated transaction keys retain immediate per-item readback so later replay in the same
      microbatch cannot retroactively change an earlier result.

    Replay, earliest-observation canonicalization, reservation, detector, episode, FIFO and audit
    semantics remain unchanged.
    """

    original_db_stage = pumpswap_writer_module._persist_prepared_batch_db_stage
    reset_pumpswap_persistence_fastpath_metrics()
    pumpswap_writer_module._persist_prepared_batch_db_stage = persist_prepared_batch_fast_v29
    try:
        return await v28.run_smoke_v28(**kwargs)
    finally:
        pumpswap_writer_module._persist_prepared_batch_db_stage = original_db_stage
        snapshot = pumpswap_persistence_fastpath_snapshot()
        trade_collision_pct = (
            (100.0 * snapshot.trade_collision_reads / snapshot.trade_insert_attempts)
            if snapshot.trade_insert_attempts
            else 0.0
        )
        lifecycle_collision_pct = (
            (100.0 * snapshot.lifecycle_collision_reads / snapshot.lifecycle_insert_attempts)
            if snapshot.lifecycle_insert_attempts
            else 0.0
        )
        total_readbacks = (
            snapshot.affected_token_batch_readbacks
            + snapshot.affected_token_repeated_key_readbacks
        )
        readbacks_per_item = (
            total_readbacks / snapshot.prepared_items
            if snapshot.prepared_items
            else 0.0
        )
        print("\nV29 OPTIMISTIC PUMPSWAP PERSISTENCE FAST-PATH DIAGNOSTIC")
        print(
            f"prepared_items={snapshot.prepared_items} "
            f"trade_insert_attempts={snapshot.trade_insert_attempts} "
            f"trade_collision_reads={snapshot.trade_collision_reads} "
            f"trade_collision_pct={trade_collision_pct:.3f}% "
            f"lifecycle_insert_attempts={snapshot.lifecycle_insert_attempts} "
            f"lifecycle_collision_reads={snapshot.lifecycle_collision_reads} "
            f"lifecycle_collision_pct={lifecycle_collision_pct:.3f}%"
        )
        print(
            f"affected_token_batch_readbacks={snapshot.affected_token_batch_readbacks} "
            f"affected_token_repeated_key_readbacks={snapshot.affected_token_repeated_key_readbacks} "
            f"total_affected_token_readbacks={total_readbacks} "
            f"readbacks_per_prepared_item={readbacks_per_item:.4f}"
        )
        print(
            "v29 changes SQL shape only: insert-first on the common new-row path, replay SELECTs "
            "only after collisions, batch readback for unique transaction keys, and immediate "
            "readback only for repeated keys that require per-item replay causality."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v29 optimized PumpSwap persistence"
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
    parser.add_argument("--continuation-batch-size", type=int, default=32)
    parser.add_argument("--continuation-batch-max-wait-ms", type=int, default=5)
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
    ):
        if getattr(args, name) <= 0:
            parser.error(f"{name.replace('_', '-')} must be positive")
    if args.pump_batch_max_wait_ms < 0:
        parser.error("pump-batch-max-wait-ms cannot be negative")
    if args.pumpswap_writer_batch_max_wait_ms < 0:
        parser.error("pumpswap-writer-batch-max-wait-ms cannot be negative")
    if args.continuation_batch_max_wait_ms < 0:
        parser.error("continuation-batch-max-wait-ms cannot be negative")

    journal_mode, synchronous = v19._enable_wal_mode()
    print("Crypto Copy Trader — Unified Market Latency Smoke v29 Optimistic PumpSwap Persistence")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(f"sqlite_journal_mode={journal_mode} sqlite_synchronous={synchronous}")
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
    asyncio.run(run_smoke_v29(**kwargs))


if __name__ == "__main__":
    main()
