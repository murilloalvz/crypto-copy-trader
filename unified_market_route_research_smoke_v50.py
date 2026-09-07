from __future__ import annotations

import argparse
import asyncio
import time

import src.pumpswap_ready_scheduler as ready_scheduler_module
from src.pumpswap_sequence_barrier_trace_v50 import (
    PumpSwapSequenceBarrierTraceV50,
    dominant_clock_v50,
)
import unified_market_execution_quote_smoke_v31 as v31
import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v20 as v20
import unified_market_latency_smoke_v30 as v30
import unified_market_route_research_smoke_v49 as v49


_BASE_V49_RUN_SMOKE = v49.run_smoke_v49


def _short_signature(value: str) -> str:
    text = str(value)
    if len(text) <= 14:
        return text or "missing"
    return f"{text[:6]}…{text[-6:]}"


def _short_assets(assets: tuple[str, ...]) -> str:
    if not assets:
        return "none"
    return ",".join(f"{asset[:10]}…" if len(asset) > 10 else asset for asset in assets)


async def run_smoke_v50(**kwargs) -> None:
    """Observe v49 without changing scheduling and attribute PumpSwap causal clocks.

    v50 is diagnostic-only. It wraps stream ingress, the v20 normalization primitive and the
    existing ReadyAssetScheduler lifecycle to reconstruct the strict global reservation watermark.
    No detector/provider/FIFO/as-of/reservation decision is changed. v49 ingress prefetch and the
    frozen v42 research path remain the executed system.
    """

    trace = PumpSwapSequenceBarrierTraceV50()

    original_stream_factory = v19.iter_pumpswap_log_notifications
    original_v19_begin = v19.begin_pumpswap_notification_normalized_v5
    original_v20_begin = v20.begin_pumpswap_notification_normalized_v5
    scheduler_class = ready_scheduler_module.ReadyAssetScheduler
    original_reserve = scheduler_class.reserve
    original_submit = scheduler_class.submit
    original_skip = scheduler_class.skip
    original_get_ready = scheduler_class.get_ready
    original_complete = scheduler_class.complete

    async def tracking_stream_factory(**stream_kwargs):
        stream = original_stream_factory(**stream_kwargs)
        try:
            async for notification in stream:
                trace.observe_ingress(notification, observed_monotonic=time.monotonic())
                yield notification
        finally:
            await stream.aclose()

    async def traced_v19_begin(notification, *args, **begin_kwargs):
        handle = await original_v19_begin(notification, *args, **begin_kwargs)
        trace.observe_normalization(notification, handle)
        return handle

    async def traced_v20_begin(notification, *args, **begin_kwargs):
        # v20 installs its own indexed_begin into v19 before the timed run. That wrapper calls the
        # function imported into the v20 module by value, so hook that lower primitive too. This is
        # observational only; the exact original arguments/result are preserved.
        handle = await original_v20_begin(notification, *args, **begin_kwargs)
        trace.observe_normalization(notification, handle)
        return handle

    def traced_reserve(self, assets):
        reservation = original_reserve(self, assets)
        trace.observe_reservation(reservation)
        return reservation

    def traced_submit(self, payload, reservation):
        trace.observe_submit_or_skip(
            reservation,
            disposition="submit",
            observed_monotonic=time.monotonic(),
        )
        return original_submit(self, payload, reservation)

    def traced_skip(self, reservation):
        trace.observe_submit_or_skip(
            reservation,
            disposition="skip",
            observed_monotonic=time.monotonic(),
        )
        return original_skip(self, reservation)

    async def traced_get_ready(self):
        work = await original_get_ready(self)
        trace.observe_ready(work)
        return work

    async def traced_complete(self, reservation):
        result = await original_complete(self, reservation)
        trace.observe_complete(reservation, observed_monotonic=time.monotonic())
        return result

    v19.iter_pumpswap_log_notifications = tracking_stream_factory
    v19.begin_pumpswap_notification_normalized_v5 = traced_v19_begin
    v20.begin_pumpswap_notification_normalized_v5 = traced_v20_begin
    scheduler_class.reserve = traced_reserve
    scheduler_class.submit = traced_submit
    scheduler_class.skip = traced_skip
    scheduler_class.get_ready = traced_get_ready
    scheduler_class.complete = traced_complete
    try:
        await _BASE_V49_RUN_SMOKE(**kwargs)
    finally:
        v19.iter_pumpswap_log_notifications = original_stream_factory
        v19.begin_pumpswap_notification_normalized_v5 = original_v19_begin
        v20.begin_pumpswap_notification_normalized_v5 = original_v20_begin
        scheduler_class.reserve = original_reserve
        scheduler_class.submit = original_submit
        scheduler_class.skip = original_skip
        scheduler_class.get_ready = original_get_ready
        scheduler_class.complete = original_complete

    snapshot = trace.snapshot()
    rows = list(snapshot.rows)
    self_normalization = [row.self_ingress_to_normalization_seconds for row in rows]
    global_barrier = [row.prefix_normalization_barrier_seconds for row in rows]
    post_prefix = [row.post_prefix_coordinator_seconds for row in rows]
    normalization_to_reservation = [row.normalization_to_reservation_seconds for row in rows]
    reservation_to_submit = [
        row.reservation_to_submit_seconds
        for row in rows
        if row.reservation_to_submit_seconds is not None
    ]
    submit_to_ready = [
        row.submit_to_dependency_ready_seconds
        for row in rows
        if row.submit_to_dependency_ready_seconds is not None
    ]
    attribution_complete = (
        snapshot.ingress_count > 0
        and snapshot.normalization_count == snapshot.ingress_count
        and snapshot.reservation_count == snapshot.ingress_count
        and snapshot.submit_or_skip_count == snapshot.reservation_count
        and len(rows) == snapshot.ingress_count
    )

    print("\nV50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC")
    print(
        f"ingress={snapshot.ingress_count} normalization={snapshot.normalization_count} "
        f"reservations={snapshot.reservation_count} submit_or_skip={snapshot.submit_or_skip_count} "
        f"dependency_ready={snapshot.ready_count} attributed_rows={len(rows)}"
    )
    print(f"trace_attribution_complete={attribution_complete}")
    print(
        f"self_ingress_to_normalization_ms {v19._latency_summary_ms(self_normalization)}"
    )
    print(
        f"global_prefix_normalization_barrier_ms {v19._latency_summary_ms(global_barrier)}"
    )
    print(
        f"post_prefix_reservation_coordinator_ms {v19._latency_summary_ms(post_prefix)}"
    )
    print(
        f"normalization_to_reservation_reconstructed_ms "
        f"{v19._latency_summary_ms(normalization_to_reservation)}"
    )
    print(
        f"reservation_to_submit_reconstructed_ms {v19._latency_summary_ms(reservation_to_submit)}"
    )
    print(
        f"submit_to_dependency_ready_ms {v19._latency_summary_ms(submit_to_ready)}"
    )
    print(f"dominant_clock={dominant_clock_v50(snapshot)}")

    print("top_global_sequence_blockers:")
    for blocker in snapshot.blockers[:10]:
        print(
            f"  seq={blocker.blocker_sequence} sig={_short_signature(blocker.blocker_signature)} "
            f"assets={_short_assets(blocker.blocker_assets)} "
            f"self_normalization_ms={blocker.blocker_ingress_to_normalization_seconds * 1000.0:.1f} "
            f"blocked_successors={blocker.blocked_successors} "
            f"successor_wait_total_ms={blocker.total_successor_barrier_seconds * 1000.0:.1f} "
            f"successor_wait_max_ms={blocker.max_successor_barrier_seconds * 1000.0:.1f}"
        )
    if not snapshot.blockers:
        print("  none")

    print(
        "v50_note=global_prefix_normalization_barrier is the wait imposed on an already-normalized "
        "successor by an earlier ingress sequence whose normalization completed later. "
        "post_prefix_reservation_coordinator is residual coordinator delay after every required "
        "predecessor normalization is available. trace_attribution_complete must be True before "
        "the dominant-clock classification is accepted. This instrumentation is observational only."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="v50 diagnostic-only PumpSwap global sequence barrier attribution"
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1500)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-batch-size", type=int, default=32)
    parser.add_argument("--pump-batch-max-wait-ms", type=int, default=25)
    parser.add_argument("--pump-prepare-workers", type=int, default=v49.V49_PUMP_PREPARE_WORKERS)
    parser.add_argument("--pumpswap-workers", type=int, default=v31.PASS_PUMPSWAP_WORKERS)
    parser.add_argument(
        "--pumpswap-prepare-submitters",
        type=int,
        default=v31.PASS_PUMPSWAP_PREPARE_SUBMITTERS,
    )
    parser.add_argument(
        "--pumpswap-prepare-executor-workers",
        type=int,
        default=v31.PASS_PUMPSWAP_PREPARE_EXECUTOR_WORKERS,
    )
    parser.add_argument("--pumpswap-writer-batch-size", type=int, default=32)
    parser.add_argument("--pumpswap-writer-batch-max-wait-ms", type=int, default=10)
    parser.add_argument("--max-concurrent-resolutions", type=int, default=18)
    parser.add_argument("--queue-size", type=int, default=5000)
    parser.add_argument("--continuation-batch-size", type=int, default=32)
    parser.add_argument("--continuation-batch-max-wait-ms", type=int, default=5)
    parser.add_argument("--default-io-workers", type=int, default=v31.PASS_DEFAULT_IO_WORKERS)
    parser.add_argument("--hydration-batch-size", type=int, default=64)
    parser.add_argument("--hydration-batch-max-wait-ms", type=int, default=5)
    parser.add_argument("--hedge-endpoints", type=int, default=2)
    parser.add_argument("--hydration-batch-workers", type=int, default=8)
    parser.add_argument("--max-hazard-episodes", type=int, default=12)
    parser.add_argument("--hazard-workers", type=int, default=2)
    parser.add_argument("--hazard-rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--max-research-episodes", type=int, default=12)
    parser.add_argument("--research-workers", type=int, default=2)
    parser.add_argument("--hazard-wait-timeout-seconds", type=int, default=20)
    parser.add_argument("--jupiter-timeout-seconds", type=int, default=5)
    parser.add_argument("--research-notional-usd", type=float, default=25.0)
    parser.add_argument("--research-slippage-bps", type=int, default=100)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.duration_seconds <= v19.MAX_SMOKE_SECONDS:
        raise SystemExit(
            f"--duration-seconds must be between 1 and {v19.MAX_SMOKE_SECONDS}"
        )
    try:
        v30.validate_capacity_profile(
            pumpswap_workers=args.pumpswap_workers,
            pump_prepare_workers=args.pump_prepare_workers,
            pumpswap_prepare_submitters=args.pumpswap_prepare_submitters,
            pumpswap_prepare_executor_workers=args.pumpswap_prepare_executor_workers,
            default_io_workers=args.default_io_workers,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.hydration_batch_workers * args.hedge_endpoints > args.max_concurrent_resolutions:
        raise SystemExit(
            "hydration-batch-workers * hedge-endpoints must not exceed max-concurrent-resolutions"
        )

    print("Crypto Copy Trader — Unified Market Route-Only Research Smoke v50")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — observational systems diagnostics only; "
        "v49 scheduling and frozen v42 market/research semantics remain unchanged."
    )
    asyncio.run(
        run_smoke_v50(
            max_research_episodes=args.max_research_episodes,
            research_workers=args.research_workers,
            hazard_wait_timeout_seconds=args.hazard_wait_timeout_seconds,
            jupiter_timeout_seconds=args.jupiter_timeout_seconds,
            research_notional_usd=args.research_notional_usd,
            research_slippage_bps=args.research_slippage_bps,
            hydration_batch_workers=args.hydration_batch_workers,
            max_hazard_episodes=args.max_hazard_episodes,
            hazard_workers=args.hazard_workers,
            hazard_rpc_timeout_seconds=args.hazard_rpc_timeout_seconds,
            hydration_batch_size=args.hydration_batch_size,
            hydration_batch_max_wait_ms=args.hydration_batch_max_wait_ms,
            hedge_endpoints=args.hedge_endpoints,
            default_io_workers=args.default_io_workers,
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
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
