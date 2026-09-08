from __future__ import annotations

import argparse
import asyncio

from src.cross_source_token_commit_lanes import CrossSourceTokenCommitLanes
from src.pumpswap_deadline_hedged_resolver_v52 import DeadlineBoundedParallelHedgedResolverV52
from src.pumpswap_latency_headroom_v3 import build_latency_headroom_report_v3
from src.pumpswap_parallel_batched_resolver_v41 import ParallelHedgedBatchedBoundedResolverV41
from src.pumpswap_resolver_latency_hardening_v3 import AsyncDurablePoolResolutionMixinV3
from src.pumpswap_resolver_wait_trace_v53 import TracedDeadlineBoundedResolverV53
from src.pumpswap_sequence_barrier_trace_v50 import PumpSwapSequenceBarrierTraceV50
from src.pumpswap_shared_transport_resolver_tailfix_v2 import SharedTransportDeadlineResolverTailfixV2
from src.pumpswap_stateful_priority_scheduler_v51 import StatefulPriorityEagerDemotingReadyAssetSchedulerV51
from src.sqlite_write_admission import sqlite_write_admission_snapshot
import unified_market_latency_smoke_v19 as v19
import unified_market_route_research_smoke_tailfix_v1 as tailfix_v1
import unified_market_route_research_smoke_tailfix_v2 as tailfix_v2
import unified_market_route_research_smoke_v50 as v50


V3_PUMP_COMMIT_WORKERS = 1
# The inherited v19 topology still owns one PumpSwap finalizer coroutine. Keep one commit executor
# worker until that upstream consumer topology is explicitly changed and proven; extra executor
# threads alone would create no concurrency and would falsely imply capacity.
V3_PUMPSWAP_COMMIT_WORKERS = 1
last_headroom_report_v3 = None


class TrackedSequenceBarrierTraceV3(PumpSwapSequenceBarrierTraceV50):
    last_instance: "TrackedSequenceBarrierTraceV3 | None" = None

    def __init__(self) -> None:
        super().__init__()
        TrackedSequenceBarrierTraceV3.last_instance = self


class V3CrossSourceTokenCommitLanes(CrossSourceTokenCommitLanes):
    last_instance: "V3CrossSourceTokenCommitLanes | None" = None

    def __init__(self) -> None:
        super().__init__(
            pump_workers=V3_PUMP_COMMIT_WORKERS,
            pumpswap_workers=V3_PUMPSWAP_COMMIT_WORKERS,
        )
        V3CrossSourceTokenCommitLanes.last_instance = self


class HardenedTracedSharedTransportResolverV3(
    AsyncDurablePoolResolutionMixinV3,
    tailfix_v2.TracedSharedTransportResolverTailfixV2,
):
    """V53 wait trace + Tailfix-v2 transport + async durable mapping stages."""

    last_instance: "HardenedTracedSharedTransportResolverV3 | None" = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        HardenedTracedSharedTransportResolverV3.last_instance = self
        TracedDeadlineBoundedResolverV53.last_instance = self
        SharedTransportDeadlineResolverTailfixV2.last_instance = self
        DeadlineBoundedParallelHedgedResolverV52.last_instance = self
        ParallelHedgedBatchedBoundedResolverV41.last_instance = self


async def run_smoke_tailfix_v3(**kwargs) -> None:
    """Run preventive latency hardening without changing market/economic semantics.

    V3 keeps Tailfix-v1 token serialization and Tailfix-v2 bounded RPC decision release, then:
    * moves resolver SQLite lookup/write/reload stages off the asyncio event loop while retaining
      same-pool single-flight until canonical durable identity exists;
    * gives pool-identity durability its own bounded highest SQLite admission priority because it is
      upstream of normalization/reservation;
    * retains the exact v50 causal clocks and emits an 80%-of-gate engineering warning before the
      official immutable 5s PumpSwap p95 gate is breached.

    The global ingress-sequence reservation watermark remains intentionally conservative: without a
    proven token identity an unresolved earlier pool may alias a later token, so removing that
    barrier would weaken per-asset FIFO causality. V3 attacks the safe root cause instead: keep the
    unknown-identity critical section short and non-blocking to the event loop.

    Detector thresholds, reservation order, per-asset FIFO, replay/as-of, provider pacing and every
    V68 economic definition remain untouched.
    """

    global last_headroom_report_v3
    last_headroom_report_v3 = None

    original_v2_resolver = tailfix_v2.TracedSharedTransportResolverTailfixV2
    original_commit_lanes = tailfix_v1.CrossSourceTokenCommitLanes
    original_trace_class = v50.PumpSwapSequenceBarrierTraceV50
    sqlite_before = sqlite_write_admission_snapshot()

    HardenedTracedSharedTransportResolverV3.last_instance = None
    V3CrossSourceTokenCommitLanes.last_instance = None
    TrackedSequenceBarrierTraceV3.last_instance = None

    tailfix_v2.TracedSharedTransportResolverTailfixV2 = HardenedTracedSharedTransportResolverV3
    tailfix_v1.CrossSourceTokenCommitLanes = V3CrossSourceTokenCommitLanes
    v50.PumpSwapSequenceBarrierTraceV50 = TrackedSequenceBarrierTraceV3

    run_error: BaseException | None = None
    try:
        await tailfix_v2.run_smoke_tailfix_v2(**kwargs)
    except BaseException as exc:
        run_error = exc
        raise
    finally:
        tailfix_v2.TracedSharedTransportResolverTailfixV2 = original_v2_resolver
        tailfix_v1.CrossSourceTokenCommitLanes = original_commit_lanes
        v50.PumpSwapSequenceBarrierTraceV50 = original_trace_class

        resolver = HardenedTracedSharedTransportResolverV3.last_instance
        trace = TrackedSequenceBarrierTraceV3.last_instance
        lanes = V3CrossSourceTokenCommitLanes.last_instance
        priority_scheduler = StatefulPriorityEagerDemotingReadyAssetSchedulerV51.last_instance

        print("\nTAILFIX V3 PREVENTIVE LATENCY HARDENING DIAGNOSTIC")
        if resolver is None:
            print("tailfix_v3_resolver_instance=missing")
            if run_error is None:
                raise RuntimeError("tailfix v3 hardened resolver was not installed")
            return
        if trace is None:
            print("tailfix_v3_sequence_trace_instance=missing")
            if run_error is None:
                raise RuntimeError("tailfix v3 sequence trace was not installed")
            return
        if lanes is None:
            print("tailfix_v3_commit_lanes_instance=missing")
            if run_error is None:
                raise RuntimeError("tailfix v3 commit lanes were not installed")
            return

        resolver_snapshot = resolver.resolver_stage_snapshot_v3()
        sequence_snapshot = trace.snapshot()
        lane_snapshot = lanes.snapshot()
        priority_snapshot = (
            priority_scheduler.priority_snapshot()
            if priority_scheduler is not None
            else None
        )
        sqlite_snapshot = sqlite_write_admission_snapshot()
        sqlite_resolution_delta = (
            sqlite_snapshot.resolution_acquisitions - sqlite_before.resolution_acquisitions
        )

        print(
            f"resolver_durable_mapping_writes={resolver_snapshot.durable_mapping_writes} "
            f"mapping_sync_started={resolver_snapshot.mapping_sync_started} "
            f"mapping_sync_admitted={resolver_snapshot.mapping_sync_admitted} "
            f"mapping_sync_completed={resolver_snapshot.mapping_sync_completed} "
            f"mapping_sync_inflight={resolver_snapshot.mapping_sync_inflight} "
            f"current_store_hits={resolver_snapshot.current_store_hits} "
            f"historical_store_hits={resolver_snapshot.historical_store_hits} "
            f"network_resolutions={resolver_snapshot.network_resolutions} "
            f"event_loop_store_calls={resolver_snapshot.event_loop_store_calls}"
        )
        print(
            "resolver_current_store_lookup_ms "
            f"{v19._latency_summary_ms(list(resolver_snapshot.current_store_lookup_seconds))}"
        )
        print(
            "resolver_historical_store_lookup_ms "
            f"{v19._latency_summary_ms(list(resolver_snapshot.historical_store_lookup_seconds))}"
        )
        print(
            "resolver_network_account_wait_ms "
            f"{v19._latency_summary_ms(list(resolver_snapshot.network_account_wait_seconds))}"
        )
        print(
            "resolver_durable_mapping_write_ms "
            f"{v19._latency_summary_ms(list(resolver_snapshot.durable_mapping_write_seconds))}"
        )
        print(
            "resolver_canonical_reload_ms "
            f"{v19._latency_summary_ms(list(resolver_snapshot.canonical_reload_seconds))}"
        )
        print(
            "resolver_pool_lock_hold_ms "
            f"{v19._latency_summary_ms(list(resolver_snapshot.pool_lock_hold_seconds))}"
        )
        print(
            f"sqlite_resolution_acquisitions_total={sqlite_snapshot.resolution_acquisitions} "
            f"sqlite_resolution_acquisitions_run_delta={sqlite_resolution_delta} "
            f"max_resolution_waiters={sqlite_snapshot.max_resolution_waiters}"
        )
        print(
            "sqlite_resolution_admission_wait_ms "
            f"{v19._latency_summary_ms(list(sqlite_snapshot.resolution_wait_seconds))}"
        )
        print(
            f"commit_lane_capacity=pump:{lane_snapshot.pump_workers},"
            f"pumpswap:{lane_snapshot.pumpswap_workers} "
            f"observed_max_parallel={lane_snapshot.max_parallel_calls} "
            f"same_token_overlap_violations={lane_snapshot.same_token_overlap_violations}"
        )

        report = build_latency_headroom_report_v3(
            sequence_snapshot=sequence_snapshot,
            resolver_snapshot=resolver_snapshot,
            priority_snapshot=priority_snapshot,
            commit_snapshot=lane_snapshot,
        )
        last_headroom_report_v3 = report
        print("\nTAILFIX V3 LATENCY HEADROOM REPORT")
        print(
            f"official_pipeline_p95_gate_ms=5000.0 early_warning_ms=4000.0 "
            f"dominant_stage={report.dominant_stage} "
            f"dominant_stage_p95_ms={report.dominant_stage_p95_seconds * 1000.0:.1f}"
        )
        for stage in report.stages:
            print(
                f"stage={stage.stage} p95_ms={stage.p95_seconds * 1000.0:.1f} "
                f"gate_share_pct={stage.share_of_official_gate_pct:.1f} "
                f"early_warning={stage.early_warning}"
            )
        warning_text = ",".join(report.warning_stages) if report.warning_stages else "none"
        print(f"early_warning_stages={warning_text}")
        print(
            "tailfix_v3_headroom_note=stage warnings are engineering-only and never replace or "
            "relax the frozen 11/11 systems gate. Stage clocks are not summed because pipeline "
            "stages can overlap. A warning means a single stage already consumes >=80% of the "
            "official 5s p95 budget; the systems wrapper will HOLD economic promotion even if the "
            "official 11/11 gate itself still passes."
        )

        if run_error is None:
            published_identities = (
                resolver_snapshot.historical_store_hits
                + resolver_snapshot.network_resolutions
            )
            if resolver_snapshot.event_loop_store_calls != 0:
                raise RuntimeError("tailfix v3 observed resolver SQLite work on the event loop")

            # Publication safety is the invariant that matters scientifically: every identity that
            # became visible to normalization must have a completed durable mapping write first.
            # A write may legitimately complete after its awaiting coroutine is cancelled at the
            # frozen deadline; such a write is durable but was never published in this run.
            if resolver_snapshot.mapping_sync_completed < published_identities:
                raise RuntimeError(
                    "tailfix v3 durable mapping publication invariant violated: published identity "
                    "without a completed durable write"
                )
            if resolver_snapshot.mapping_sync_completed > resolver_snapshot.mapping_sync_admitted:
                raise RuntimeError("tailfix v3 mapping sync completion exceeded admitted writes")
            if resolver_snapshot.mapping_sync_admitted > resolver_snapshot.mapping_sync_started:
                raise RuntimeError("tailfix v3 mapping sync admission exceeded started writes")
            if resolver_snapshot.mapping_sync_inflight < 0:
                raise RuntimeError("tailfix v3 mapping sync inflight accounting became negative")

            # The global gate increments immediately before the resolver thread records its local
            # admitted counter. At snapshot time an in-flight worker can therefore make the global
            # delta exceed the local admitted count by at most the number of local in-flight writes.
            if sqlite_resolution_delta < resolver_snapshot.mapping_sync_admitted:
                raise RuntimeError(
                    "tailfix v3 resolution-priority admission undercount: local admitted write was "
                    "not observed by the global gate"
                )
            if sqlite_resolution_delta > (
                resolver_snapshot.mapping_sync_admitted + resolver_snapshot.mapping_sync_inflight
            ):
                raise RuntimeError(
                    "tailfix v3 resolution-priority admission overcount beyond in-flight tolerance"
                )
            if lane_snapshot.pump_workers != V3_PUMP_COMMIT_WORKERS:
                raise RuntimeError("tailfix v3 Pump commit lane capacity mismatch")
            if lane_snapshot.pumpswap_workers != V3_PUMPSWAP_COMMIT_WORKERS:
                raise RuntimeError("tailfix v3 PumpSwap commit lane capacity mismatch")
            if lane_snapshot.same_token_overlap_violations != 0:
                raise RuntimeError("tailfix v3 same-token serialization invariant violated")
            if lane_snapshot.max_parallel_calls > (
                V3_PUMP_COMMIT_WORKERS + V3_PUMPSWAP_COMMIT_WORKERS
            ):
                raise RuntimeError("tailfix v3 commit lanes exceeded configured capacity")


def build_parser() -> argparse.ArgumentParser:
    parser = tailfix_v2.build_parser()
    parser.description = (
        "Systems-only Tailfix v3: async durable pool identity stages, resolution-priority SQLite "
        "admission, inherited bounded RPC transport and proactive latency headroom diagnostics"
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    print("Crypto Copy Trader — Route Research Systems Tailfix v3")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — preventive systems hardening only; detector and "
        "economics frozen."
    )
    asyncio.run(run_smoke_tailfix_v3(**vars(args)))


if __name__ == "__main__":
    main()
