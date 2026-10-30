from __future__ import annotations

import argparse
import asyncio

from src.pumpswap_stateful_priority_scheduler_v51 import (
    StatefulPriorityEagerDemotingReadyAssetSchedulerV51,
)
import unified_market_latency_smoke_v19 as v19
import unified_market_route_research_smoke_v42 as v42
import unified_market_route_research_smoke_v50 as v50


_BASE_V50_RUN_SMOKE = v50.run_smoke_v50


async def run_smoke_v51(**kwargs) -> None:
    """Run the v49/v50 systems path with v51 stateful-priority ready selection.

    Only the ready-queue ordering among already-ready PumpSwap jobs changes. Stateful work
    keeps the inherited v42/v34 reservation/FIFO semantics. Proven-demoted continuation
    audits remain visible but no longer sit ahead of unrelated stateful episode work.
    """

    original_scheduler_class = v42.EagerDemotingReadyAssetSchedulerV42
    StatefulPriorityEagerDemotingReadyAssetSchedulerV51.last_instance = None
    v42.EagerDemotingReadyAssetSchedulerV42 = (
        StatefulPriorityEagerDemotingReadyAssetSchedulerV51
    )
    try:
        await _BASE_V50_RUN_SMOKE(**kwargs)
    finally:
        v42.EagerDemotingReadyAssetSchedulerV42 = original_scheduler_class

    scheduler = StatefulPriorityEagerDemotingReadyAssetSchedulerV51.last_instance
    print("\nV51 STATEFUL-PRIORITY READY-QUEUE DIAGNOSTIC")
    if scheduler is None:
        print("v51_scheduler_instance=missing")
        return

    snapshot = scheduler.priority_snapshot()
    print(
        f"stateful_enqueued={snapshot.stateful_enqueued} "
        f"demoted_enqueued={snapshot.demoted_enqueued} "
        f"stateful_dequeued={snapshot.stateful_dequeued} "
        f"demoted_dequeued={snapshot.demoted_dequeued} "
        f"stateful_overtakes_demoted={snapshot.stateful_overtakes_demoted}"
    )
    print(
        f"stateful_backlog_high_water={snapshot.stateful_backlog_high_water} "
        f"demoted_backlog_high_water={snapshot.demoted_backlog_high_water} "
        f"stateful_backlog={snapshot.stateful_backlog} "
        f"demoted_backlog={snapshot.demoted_backlog}"
    )
    print(
        "stateful_ready_queue_wait_ms "
        f"{v19._latency_summary_ms(snapshot.stateful_queue_wait_seconds)}"
    )
    print(
        "demoted_ready_queue_wait_ms "
        f"{v19._latency_summary_ms(snapshot.demoted_queue_wait_seconds)}"
    )
    print(
        "v51_note=priority is granted only after the inherited v34 proof has converted a "
        "continuation reservation into a causal skip. One PumpSwap finalizer and the shared "
        "stateful commit executor remain unchanged; FIFO is stable within each ready class."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = v50.build_parser()
    parser.description = (
        "v51 systems-only route smoke with stateful-ready priority over proven continuation audits"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print("Crypto Copy Trader — Unified Market Route-Only Research Smoke v51")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — v49 scheduling + v50 causal clocks + "
        "v51 stateful-priority ready selection; no economic forward collection."
    )
    asyncio.run(
        run_smoke_v51(
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
