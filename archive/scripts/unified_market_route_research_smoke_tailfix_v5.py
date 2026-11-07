from __future__ import annotations

import src.pumpswap_deferred_persistence_v5 as deferred_persistence
from src.pumpswap_causal_normalization_v5 import prepare_pumpswap_notification_causal_v5
from src.pumpswap_normalization_resolver_v5 import (
    CoalescedNormalizationPoolResolutionMixinV5,
)
from src.pumpswap_writer_headroom_v5 import InstrumentedPumpSwapSQLiteWriterV5
import unified_market_latency_smoke_v19 as v19
import unified_market_route_research_smoke_tailfix_v3 as tailfix_v3
import unified_market_route_research_smoke_tailfix_v4 as tailfix_v4


V5_WRITER_RESULT_WAIT_WARNING_SECONDS = 4.0
V5_WRITER_QUEUE_P95_WARNING_SHARE = 0.80

last_writer_headroom_v5 = None
last_writer_warning_v5 = False
last_writer_queue_p95_share_v5 = 0.0
last_resolver_snapshot_v5 = None
last_resolver_v3_snapshot_v5 = None


class HardenedNormalizationResolverV5(
    CoalescedNormalizationPoolResolutionMixinV5,
    tailfix_v3.HardenedTracedSharedTransportResolverV3,
):
    """Tailfix-v3 transport/durability plus normalization-specific same-pool coalescing."""

    last_instance: "HardenedNormalizationResolverV5 | None" = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        HardenedNormalizationResolverV5.last_instance = self
        type(self).last_instance = self


async def run_smoke_tailfix_v5(**kwargs) -> None:
    """Run v4 with the normalization stampede removed and sustained writer headroom measured.

    V4 proved throughput can drain completely, but its per-event PumpSwap p95 regressed because
    resolution fairness was forced to arbitrate hundreds of duplicate/same-pool identity writes.
    The live evidence showed 560 mapping write attempts with 238 collision reads (42.5%), while the
    global normalization barrier reached ~17.4s p95.

    V5 changes the cause rather than tuning the fairness constant:

    * current-run cache/store identity already durably learned may be reused by older queued
      notifications; the normalized event remains unavailable until mapping.observed_at;
    * prior-run historical lookup stays strictly bounded by the notification observed time;
    * historical promotion occurs only after entering the existing per-pool single-flight lock;
    * queued same-pool notifications therefore reuse the first durable mapping instead of issuing
      duplicate promotion/RPC writes;
    * CreatePoolEvent mapping persistence is awaited asynchronously, eliminating the remaining
      synchronous pool-store write from the normalization event loop;
    * writer promotion headroom uses p95 queue depth and p95 actual result wait rather than one
      transient queue high-water point.

    V4's SQLite fairness policy, V3/V2 transport ceilings, detector thresholds, reservation FIFO,
    replay semantics, provider pacing and every V68 economic definition remain unchanged.
    """

    global last_writer_headroom_v5, last_writer_warning_v5
    global last_writer_queue_p95_share_v5, last_resolver_snapshot_v5
    global last_resolver_v3_snapshot_v5

    last_writer_headroom_v5 = None
    last_writer_warning_v5 = False
    last_writer_queue_p95_share_v5 = 0.0
    last_resolver_snapshot_v5 = None
    last_resolver_v3_snapshot_v5 = None

    original_resolver_class = tailfix_v3.HardenedTracedSharedTransportResolverV3
    original_prepare = deferred_persistence.prepare_pumpswap_notification_normalized_v3
    original_v4_writer_class = tailfix_v4.InstrumentedPumpSwapSQLiteWriterV4

    HardenedNormalizationResolverV5.last_instance = None
    InstrumentedPumpSwapSQLiteWriterV5.last_instance = None

    tailfix_v3.HardenedTracedSharedTransportResolverV3 = HardenedNormalizationResolverV5
    deferred_persistence.prepare_pumpswap_notification_normalized_v3 = (
        prepare_pumpswap_notification_causal_v5
    )
    tailfix_v4.InstrumentedPumpSwapSQLiteWriterV4 = InstrumentedPumpSwapSQLiteWriterV5

    run_error: BaseException | None = None
    try:
        await tailfix_v4.run_smoke_tailfix_v4(**kwargs)
    except BaseException as exc:
        run_error = exc
        raise
    finally:
        resolver = HardenedNormalizationResolverV5.last_instance
        writer = InstrumentedPumpSwapSQLiteWriterV5.last_instance

        tailfix_v4.InstrumentedPumpSwapSQLiteWriterV4 = original_v4_writer_class
        deferred_persistence.prepare_pumpswap_notification_normalized_v3 = original_prepare
        tailfix_v3.HardenedTracedSharedTransportResolverV3 = original_resolver_class

        resolver_v5_snapshot = (
            resolver.normalization_resolver_snapshot_v5() if resolver is not None else None
        )
        resolver_v3_snapshot = (
            resolver.resolver_stage_snapshot_v3() if resolver is not None else None
        )
        writer_snapshot = writer.headroom_snapshot_v5() if writer is not None else None

        last_resolver_snapshot_v5 = resolver_v5_snapshot
        last_resolver_v3_snapshot_v5 = resolver_v3_snapshot
        last_writer_headroom_v5 = writer_snapshot

        pumpswap_workers = max(1, int(kwargs.get("pumpswap_workers", 1)))
        if writer_snapshot is not None:
            last_writer_queue_p95_share_v5 = (
                float(writer_snapshot.queue_depth_p95) / pumpswap_workers
            )
            drain_warning = (
                writer_snapshot.base.pending_at_close != 0
                or writer_snapshot.base.queue_before_close != 0
            )
            result_wait_warning = (
                writer_snapshot.result_wait_p95_seconds
                >= V5_WRITER_RESULT_WAIT_WARNING_SECONDS
            )
            sustained_queue_warning = (
                last_writer_queue_p95_share_v5 >= V5_WRITER_QUEUE_P95_WARNING_SHARE
            )
            last_writer_warning_v5 = (
                drain_warning or result_wait_warning or sustained_queue_warning
            )

        print("\nTAILFIX V5 CAUSAL NORMALIZATION / SUSTAINED THROUGHPUT DIAGNOSTIC")
        if resolver_v5_snapshot is None or resolver_v3_snapshot is None:
            print("v5_resolver_instance=missing")
        else:
            print(
                f"normalization_cache_hits={resolver_v5_snapshot.normalization_cache_hits} "
                f"normalization_current_store_hits={resolver_v5_snapshot.normalization_current_store_hits} "
                f"historical_promotions={resolver_v5_snapshot.normalization_historical_promotions} "
                f"network_resolutions={resolver_v5_snapshot.normalization_network_resolutions}"
            )
            print(
                f"delayed_availability_reuses={resolver_v5_snapshot.delayed_availability_reuses} "
                f"coalesced_after_pool_lock_reuses={resolver_v5_snapshot.coalesced_after_pool_lock_reuses} "
                f"create_pool_durable_learns={resolver_v5_snapshot.create_pool_durable_learns} "
                f"create_pool_reuses={resolver_v5_snapshot.create_pool_reuses}"
            )
            print(
                f"mapping_sync_started={resolver_v3_snapshot.mapping_sync_started} "
                f"mapping_sync_completed={resolver_v3_snapshot.mapping_sync_completed} "
                f"mapping_sync_inflight={resolver_v3_snapshot.mapping_sync_inflight}"
            )

        if writer_snapshot is None:
            print("v5_writer_headroom_instance=missing")
        else:
            print(
                f"writer_queue_depth_p50={writer_snapshot.queue_depth_p50:.1f} "
                f"writer_queue_depth_p95={writer_snapshot.queue_depth_p95:.1f} "
                f"writer_queue_high_water={writer_snapshot.base.queue_high_water} "
                f"writer_pending_at_close={writer_snapshot.base.pending_at_close}"
            )
            print(
                f"writer_queue_wait_p95_ms={writer_snapshot.queue_wait_p95_seconds * 1000.0:.1f} "
                f"writer_result_wait_p95_ms={writer_snapshot.result_wait_p95_seconds * 1000.0:.1f} "
                f"writer_batch_service_p95_ms={writer_snapshot.batch_service_p95_seconds * 1000.0:.1f}"
            )
            print(
                f"writer_queue_p95_pressure_share_pct={last_writer_queue_p95_share_v5 * 100.0:.1f} "
                f"writer_sustained_pressure_warning={last_writer_warning_v5} "
                f"queue_p95_warning_threshold_pct={V5_WRITER_QUEUE_P95_WARNING_SHARE * 100.0:.1f} "
                f"result_wait_warning_ms={V5_WRITER_RESULT_WAIT_WARNING_SECONDS * 1000.0:.1f}"
            )

        print(
            "tailfix_v5_note=V5 does not relax the 5s systems gate or V4 fairness. It removes "
            "same-pool duplicate resolution work, keeps historical evidence strict, clamps delayed "
            "current-run identity availability into event observed_at, moves CreatePoolEvent store "
            "work off-loop, and replaces max-only writer pressure with sustained p95 evidence."
        )

        if run_error is None:
            if resolver_v5_snapshot is None or resolver_v3_snapshot is None:
                raise RuntimeError("tailfix v5 normalization resolver was not installed")
            if writer_snapshot is None:
                raise RuntimeError("tailfix v5 writer headroom instrumentation was not installed")
            published_new_identity = (
                resolver_v5_snapshot.normalization_historical_promotions
                + resolver_v5_snapshot.normalization_network_resolutions
                + resolver_v5_snapshot.create_pool_durable_learns
            )
            if resolver_v3_snapshot.mapping_sync_completed < published_new_identity:
                raise RuntimeError(
                    "tailfix v5 published normalization identity without completed durable mapping"
                )
            if resolver_v3_snapshot.mapping_sync_inflight < 0:
                raise RuntimeError("tailfix v5 mapping sync inflight accounting became negative")
            if writer_snapshot.base.completed > writer_snapshot.base.submitted:
                raise RuntimeError("tailfix v5 writer completion exceeded submissions")


def build_parser():
    parser = tailfix_v4.build_parser()
    parser.description = (
        "Systems-only Tailfix v5: v4 throughput profile plus same-pool normalization coalescing, "
        "delayed-availability-safe current-run reuse, async CreatePoolEvent learning and sustained "
        "writer p95 headroom"
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    print("Crypto Copy Trader — Route Research Systems Tailfix v5")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — causal normalization/throughput hardening only; "
        "detector and economics frozen."
    )
    import asyncio

    asyncio.run(run_smoke_tailfix_v5(**vars(args)))


if __name__ == "__main__":
    main()
