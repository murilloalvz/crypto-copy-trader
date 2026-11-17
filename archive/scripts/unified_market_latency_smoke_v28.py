from __future__ import annotations

import argparse
import asyncio
import functools

import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v27 as v27
import src.market_trigger_continuation_writer as continuation_writer_module
import src.pumpswap_concurrent_resolver as pumpswap_concurrent_resolver
import src.pumpswap_normalized_persistence_v4 as pumpswap_writer_module
import src.pumpswap_reusable_resolver as pumpswap_reusable_resolver
import src.pumpswap_stream as pumpswap_stream
from src import database
from src.market_observation_store import ensure_market_observation_schema
from src.market_opportunity_episode_store import ensure_market_opportunity_episode_schema
from src.opportunity_enrichment_store import ensure_opportunity_enrichment_schema
from src.pumpswap_pool_store import ensure_pumpswap_pool_schema
from src.sqlite_write_admission import (
    AUDIT_PRIORITY,
    CAUSAL_PRIORITY,
    reset_sqlite_write_admission_metrics,
    sqlite_write_admission,
    sqlite_write_admission_snapshot,
)


def _gated(function, priority: str):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        with sqlite_write_admission(priority):
            return function(*args, **kwargs)

    return wrapped


def _prewarm_write_schemas() -> None:
    # Schema DDL is intentionally outside the timed acquisition window. These schemas are
    # process/run infrastructure, not live notification work.
    ensure_market_observation_schema()
    ensure_market_opportunity_episode_schema()
    ensure_opportunity_enrichment_schema()
    ensure_pumpswap_pool_schema()


async def run_smoke_v28(**kwargs):
    """Run v27 with explicit prioritized admission to SQLite's single physical writer.

    v27 correctly separated episode-openers from continuation hits, but its independent
    continuation writer still raced Pump/PumpSwap/episode writers for the same SQLite WAL writer.
    v28 keeps every v27 detector/replay/causal rule and changes only writer admission:

    * Pump/PumpSwap observation persistence, pool mapping, episode opening and enrichment admission
      are causal-high priority;
    * continuation audit batches are audit-low priority;
    * audit work yields to waiting causal work, but receives a bounded starvation escape from the
      shared admission gate so long collections do not grow audit memory without bound;
    * reads are untouched and remain concurrent under WAL.
    """

    _prewarm_write_schemas()
    reset_sqlite_write_admission_metrics()

    originals = {
        "pump_persist": v19.persist_pump_notifications_microbatch,
        "pumpswap_db_stage": pumpswap_writer_module._persist_prepared_batch_db_stage,
        "assign_trigger": v27.assign_market_opportunity_trigger,
        "continuation_db_stage": continuation_writer_module._persist_continuation_batch_db_stage,
        "stream_pool_record": pumpswap_stream.record_pumpswap_pool_mapping,
        "reusable_pool_record": pumpswap_reusable_resolver.record_pumpswap_pool_mapping,
        "concurrent_pool_record": pumpswap_concurrent_resolver.record_pumpswap_pool_mapping,
        "enrichment_admit": v19.admit_opportunity_episode,
    }

    v19.persist_pump_notifications_microbatch = _gated(
        originals["pump_persist"], CAUSAL_PRIORITY
    )
    pumpswap_writer_module._persist_prepared_batch_db_stage = _gated(
        originals["pumpswap_db_stage"], CAUSAL_PRIORITY
    )
    v27.assign_market_opportunity_trigger = _gated(
        originals["assign_trigger"], CAUSAL_PRIORITY
    )
    continuation_writer_module._persist_continuation_batch_db_stage = _gated(
        originals["continuation_db_stage"], AUDIT_PRIORITY
    )
    gated_pool_record = _gated(originals["stream_pool_record"], CAUSAL_PRIORITY)
    pumpswap_stream.record_pumpswap_pool_mapping = gated_pool_record
    # These modules imported the same store function by value, so patch their globals too.
    pumpswap_reusable_resolver.record_pumpswap_pool_mapping = gated_pool_record
    pumpswap_concurrent_resolver.record_pumpswap_pool_mapping = gated_pool_record
    v19.admit_opportunity_episode = _gated(
        originals["enrichment_admit"], CAUSAL_PRIORITY
    )

    try:
        return await v27.run_smoke_v27(**kwargs)
    finally:
        v19.persist_pump_notifications_microbatch = originals["pump_persist"]
        pumpswap_writer_module._persist_prepared_batch_db_stage = originals["pumpswap_db_stage"]
        v27.assign_market_opportunity_trigger = originals["assign_trigger"]
        continuation_writer_module._persist_continuation_batch_db_stage = originals[
            "continuation_db_stage"
        ]
        pumpswap_stream.record_pumpswap_pool_mapping = originals["stream_pool_record"]
        pumpswap_reusable_resolver.record_pumpswap_pool_mapping = originals[
            "reusable_pool_record"
        ]
        pumpswap_concurrent_resolver.record_pumpswap_pool_mapping = originals[
            "concurrent_pool_record"
        ]
        v19.admit_opportunity_episode = originals["enrichment_admit"]

        snapshot = sqlite_write_admission_snapshot()
        print("\nV28 PRIORITIZED SQLITE WRITE ADMISSION DIAGNOSTIC")
        print(
            f"causal_acquisitions={snapshot.causal_acquisitions} "
            f"audit_acquisitions={snapshot.audit_acquisitions} "
            f"audit_forced_after_starvation={snapshot.audit_forced_after_starvation} "
            f"max_causal_waiters={snapshot.max_causal_waiters} "
            f"max_audit_waiters={snapshot.max_audit_waiters}"
        )
        print(
            f"sqlite_causal_admission_wait_ms "
            f"{v19._latency_summary_ms(snapshot.causal_wait_seconds)}"
        )
        print(
            f"sqlite_audit_admission_wait_ms "
            f"{v19._latency_summary_ms(snapshot.audit_wait_seconds)}"
        )
        print(
            "v28 serializes only SQLite writer admission. Causal work has priority; continuation "
            "audit is allowed through after bounded starvation so audit durability remains live. "
            "No detector/provider/as_of/FIFO/episode-window rule changes relative to v27."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified market latency smoke v28 prioritized SQLite writer admission"
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
    print("Crypto Copy Trader — Unified Market Latency Smoke v28 Prioritized SQLite Admission")
    print("Mode: PAPER / RESEARCH / READ ONLY — no signing or transaction submission.")
    print(
        f"run_key={args.run_key} duration={args.duration_seconds}s commitment={args.commitment} "
        f"pump_batch_size={args.pump_batch_size} pump_batch_max_wait_ms={args.pump_batch_max_wait_ms} "
        f"pump_prepare_workers={args.pump_prepare_workers} pumpswap_workers={args.pumpswap_workers} "
        f"pumpswap_writer_batch_size={args.pumpswap_writer_batch_size} "
        f"pumpswap_writer_batch_max_wait_ms={args.pumpswap_writer_batch_max_wait_ms} "
        f"pumpswap_prepare_submitters={args.pumpswap_prepare_submitters} "
        f"pumpswap_prepare_executor_workers={args.pumpswap_prepare_executor_workers} "
        f"continuation_batch_size={args.continuation_batch_size} "
        f"continuation_batch_max_wait_ms={args.continuation_batch_max_wait_ms} "
        f"sqlite_transaction_mode=IMMEDIATE sqlite_busy_timeout_ms={int(database._SQLITE_BUSY_TIMEOUT_SECONDS * 1000)} "
        f"sqlite_write_admission=causal_priority_audit_bounded_starvation "
        f"max_hydrations={args.max_hydrations} queue_size={args.queue_size} "
        f"sqlite_journal_mode={journal_mode} sqlite_synchronous={synchronous}"
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
        continuation_batch_size=args.continuation_batch_size,
        continuation_batch_max_wait_ms=args.continuation_batch_max_wait_ms,
    )
    asyncio.run(run_smoke_v28(**kwargs))


if __name__ == "__main__":
    main()
