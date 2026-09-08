from __future__ import annotations

import argparse

import src.sqlite_write_admission as sqlite_admission_module
from src.pumpswap_pool_mapping_fastpath_v4 import (
    pumpswap_pool_mapping_fastpath_snapshot_v4,
    record_pumpswap_pool_mapping_fast_v4,
    reset_pumpswap_pool_mapping_fastpath_metrics_v4,
)
from src.pumpswap_writer_pressure_v4 import (
    InstrumentedPumpSwapSQLiteWriterV4,
    PumpSwapWriterPressureSnapshotV4,
)
import unified_market_latency_smoke_v19 as v19
import unified_market_route_research_smoke_tailfix_v3 as tailfix_v3


V4_RESOLUTION_MAX_CONSECUTIVE_WITH_CAUSAL_WAITING = 1
V4_WRITER_PRESSURE_WARNING_SHARE = 0.80

last_writer_pressure_v4: PumpSwapWriterPressureSnapshotV4 | None = None
last_writer_pressure_warning_v4 = False
last_writer_pressure_share_v4 = 0.0
last_fastpath_snapshot_v4 = None
last_fairness_snapshot_v4 = None


async def run_smoke_tailfix_v4(**kwargs) -> None:
    """Run v3 with bounded SQLite fairness and optimistic pool-identity persistence.

    The failed v3 live run showed healthy per-event latency but poor end-of-window drain:
    PumpSwap pipeline p95 was ~1.9s while 224 observation writes remained queued and all 256
    persistence workers could become occupied. V4 addresses that capacity class without changing
    the detector or causal ordering:

    * pool-identity writes keep higher priority, but when a causal writer is already waiting they
      may receive at most one consecutive grant before the causal writer gets a turn;
    * the dominant fresh-run pool mapping path uses INSERT OR IGNORE first and performs the replay
      SELECT only on a UNIQUE collision, preserving earliest-observation/conflict semantics;
    * the authoritative PumpSwap observation writer is behaviorally unchanged but instrumented for
      queue high-water, completion pressure and microbatch utilization;
    * the v3 latency headroom guard remains fully active.

    There is still exactly one physical SQLite writer at a time. No worker count, detector threshold,
    provider pacing, reservation/FIFO, replay/as-of or V68 economic definition changes here.
    """

    global last_writer_pressure_v4, last_writer_pressure_warning_v4
    global last_writer_pressure_share_v4, last_fastpath_snapshot_v4, last_fairness_snapshot_v4

    last_writer_pressure_v4 = None
    last_writer_pressure_warning_v4 = False
    last_writer_pressure_share_v4 = 0.0
    last_fastpath_snapshot_v4 = None
    last_fairness_snapshot_v4 = None

    gate = sqlite_admission_module._GLOBAL_WRITE_ADMISSION
    if not gate.is_idle():
        raise RuntimeError("tailfix v4 cannot change SQLite fairness while writer work is active")
    original_fairness_limit = gate.resolution_max_consecutive_when_causal_waiting
    original_pool_record = tailfix_v3.pumpswap_pool_store.record_pumpswap_pool_mapping
    original_writer_class = v19.PumpSwapSQLiteThreadedMicrobatchWriter

    reset_pumpswap_pool_mapping_fastpath_metrics_v4()
    InstrumentedPumpSwapSQLiteWriterV4.last_instance = None
    gate.resolution_max_consecutive_when_causal_waiting = (
        V4_RESOLUTION_MAX_CONSECUTIVE_WITH_CAUSAL_WAITING
    )
    tailfix_v3.pumpswap_pool_store.record_pumpswap_pool_mapping = (
        record_pumpswap_pool_mapping_fast_v4
    )
    v19.PumpSwapSQLiteThreadedMicrobatchWriter = InstrumentedPumpSwapSQLiteWriterV4

    run_error: BaseException | None = None
    try:
        await tailfix_v3.run_smoke_tailfix_v3(**kwargs)
    except BaseException as exc:
        run_error = exc
        raise
    finally:
        writer = InstrumentedPumpSwapSQLiteWriterV4.last_instance
        fair_snapshot = sqlite_admission_module.sqlite_write_admission_snapshot()
        fast_snapshot = pumpswap_pool_mapping_fastpath_snapshot_v4()

        if writer is not None:
            writer_snapshot = writer.pressure_snapshot_v4()
        else:
            writer_snapshot = None

        last_writer_pressure_v4 = writer_snapshot
        last_fastpath_snapshot_v4 = fast_snapshot
        last_fairness_snapshot_v4 = fair_snapshot

        pumpswap_workers = max(1, int(kwargs.get("pumpswap_workers", 1)))
        if writer_snapshot is not None:
            last_writer_pressure_share_v4 = (
                writer_snapshot.queue_high_water / pumpswap_workers
            )
            last_writer_pressure_warning_v4 = (
                last_writer_pressure_share_v4 >= V4_WRITER_PRESSURE_WARNING_SHARE
            )

        # Restore by-value seams first. The shared gate object itself is retained so any late
        # deadline cleanup thread can never escape the one-writer admission lock.
        v19.PumpSwapSQLiteThreadedMicrobatchWriter = original_writer_class
        tailfix_v3.pumpswap_pool_store.record_pumpswap_pool_mapping = original_pool_record
        gate.resolution_max_consecutive_when_causal_waiting = original_fairness_limit

        print("\nTAILFIX V4 PERSISTENCE THROUGHPUT HARDENING DIAGNOSTIC")
        print(
            f"resolution_fairness_limit={V4_RESOLUTION_MAX_CONSECUTIVE_WITH_CAUSAL_WAITING} "
            f"resolution_fairness_blocks={fair_snapshot.resolution_fairness_blocks} "
            f"max_consecutive_resolution_grants={fair_snapshot.max_consecutive_resolution_grants} "
            f"resolution_acquisitions={fair_snapshot.resolution_acquisitions} "
            f"causal_acquisitions={fair_snapshot.causal_acquisitions}"
        )
        collision_pct = (
            100.0 * fast_snapshot.collision_reads / fast_snapshot.insert_attempts
            if fast_snapshot.insert_attempts
            else 0.0
        )
        print(
            f"pool_mapping_insert_attempts={fast_snapshot.insert_attempts} "
            f"pool_mapping_collision_reads={fast_snapshot.collision_reads} "
            f"pool_mapping_collision_pct={collision_pct:.3f}% "
            f"earliest_observed_updates={fast_snapshot.earliest_observed_updates} "
            f"identity_conflicts={fast_snapshot.identity_conflicts} "
            f"canonical_replacements={fast_snapshot.canonical_replacements}"
        )
        if writer_snapshot is None:
            print("v4_writer_pressure_instance=missing")
        else:
            print(
                f"writer_submitted={writer_snapshot.submitted} "
                f"writer_completed={writer_snapshot.completed} "
                f"writer_pending_at_close={writer_snapshot.pending_at_close} "
                f"writer_queue_high_water={writer_snapshot.queue_high_water} "
                f"writer_queue_before_close={writer_snapshot.queue_before_close}"
            )
            print(
                f"writer_batches={writer_snapshot.batch_count} "
                f"writer_avg_batch_size={writer_snapshot.average_batch_size:.2f} "
                f"writer_max_batch_size={writer_snapshot.max_batch_size} "
                f"writer_configured_batch_size={writer_snapshot.configured_batch_size} "
                f"writer_batch_fill_pct={writer_snapshot.batch_fill_pct:.1f}"
            )
            print(
                f"writer_queue_pressure_share_pct={last_writer_pressure_share_v4 * 100.0:.1f} "
                f"writer_queue_pressure_early_warning={last_writer_pressure_warning_v4} "
                f"warning_threshold_pct={V4_WRITER_PRESSURE_WARNING_SHARE * 100.0:.1f}"
            )
        print(
            "tailfix_v4_note=resolution identity remains durable before publication, but high-priority "
            "mapping writes can no longer starve an already-waiting causal batch indefinitely. The "
            "pool mapping SQL fast path removes the dominant fresh-row pre-read only; collision and "
            "conflict semantics remain authoritative. Writer pressure is diagnostic/promotion-only."
        )

        if run_error is None:
            if writer_snapshot is None:
                raise RuntimeError("tailfix v4 observation writer instrumentation was not installed")
            if fast_snapshot.collision_reads > fast_snapshot.insert_attempts:
                raise RuntimeError("tailfix v4 pool mapping collision accounting is impossible")
            if writer_snapshot.completed > writer_snapshot.submitted:
                raise RuntimeError("tailfix v4 writer completion accounting exceeded submissions")
            if (
                fair_snapshot.resolution_max_consecutive_when_causal_waiting
                != V4_RESOLUTION_MAX_CONSECUTIVE_WITH_CAUSAL_WAITING
            ):
                raise RuntimeError("tailfix v4 SQLite fairness policy was not active")
            if (
                fair_snapshot.max_consecutive_resolution_grants
                > V4_RESOLUTION_MAX_CONSECUTIVE_WITH_CAUSAL_WAITING
            ):
                raise RuntimeError("tailfix v4 resolution fairness burst bound was exceeded")


def build_parser() -> argparse.ArgumentParser:
    parser = tailfix_v3.build_parser()
    parser.description = (
        "Systems-only Tailfix v4: v3 latency hardening plus bounded SQLite resolution fairness, "
        "optimistic durable pool mapping writes and PumpSwap writer pressure telemetry"
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    print("Crypto Copy Trader — Route Research Systems Tailfix v4")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — persistence throughput hardening only; detector and "
        "economics frozen."
    )
    import asyncio

    asyncio.run(run_smoke_tailfix_v4(**vars(args)))


if __name__ == "__main__":
    main()
