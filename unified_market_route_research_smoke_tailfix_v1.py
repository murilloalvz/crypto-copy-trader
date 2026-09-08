from __future__ import annotations

import argparse
import asyncio

from src.cross_source_token_commit_lanes import CrossSourceTokenCommitLanes
import unified_market_latency_smoke_v19 as v19
import unified_market_route_research_smoke_v54 as v54


_BASE_V54_RUN_SMOKE = v54.run_smoke_v54


async def run_smoke_tailfix_v1(**kwargs) -> None:
    """Run frozen v54 with Pump/PumpSwap stateful commits split by source and locked by token.

    The v54 detector, reservation, continuation proof, provider pacing, research decision,
    and systems gates are untouched. Only the inherited shared one-thread stateful commit
    executor is replaced at the `_run_sync_stage` seam by two one-thread source lanes.
    Jobs that touch the same trigger token share a process-local lock across both lanes;
    unrelated Pump and PumpSwap tokens may execute concurrently.
    """

    inherited_runner = v19._run_sync_stage
    lanes = CrossSourceTokenCommitLanes()

    async def routed_sync_stage(function, /, *args, executor=None, **stage_kwargs):
        return await lanes.run_sync_stage(
            inherited_runner,
            function,
            *args,
            executor=executor,
            **stage_kwargs,
        )

    v19._run_sync_stage = routed_sync_stage
    run_error: BaseException | None = None
    try:
        await _BASE_V54_RUN_SMOKE(**kwargs)
    except BaseException as exc:
        run_error = exc
        raise
    finally:
        v19._run_sync_stage = inherited_runner
        snapshot = lanes.snapshot()
        lanes.close()

        print("\nTAILFIX V1 CROSS-SOURCE TOKEN COMMIT LANES")
        print(
            f"pump_calls={snapshot.pump_calls} "
            f"pumpswap_calls={snapshot.pumpswap_calls} "
            f"fallback_calls={snapshot.fallback_calls} "
            f"max_parallel_calls={snapshot.max_parallel_calls} "
            f"same_token_overlap_violations={snapshot.same_token_overlap_violations}"
        )
        print(
            "pump_commit_lane_queue_wait_ms "
            f"{v19._latency_summary_ms(list(snapshot.pump_lane_queue_wait_seconds))}"
        )
        print(
            "pumpswap_commit_lane_queue_wait_ms "
            f"{v19._latency_summary_ms(list(snapshot.pumpswap_lane_queue_wait_seconds))}"
        )
        print(
            "cross_source_token_lock_wait_ms "
            f"{v19._latency_summary_ms(list(snapshot.token_lock_wait_seconds))}"
        )
        print(
            "stateful_commit_service_ms "
            f"{v19._latency_summary_ms(list(snapshot.service_seconds))}"
        )
        print(
            "tailfix_v1_note=Pump and PumpSwap stateful finalizers use separate bounded one-thread "
            "lanes, while every trigger token is serialized across both sources. Multi-token work "
            "locks the sorted token set. Detector, first-persisted episode semantics, continuation "
            "proofs, reservation FIFO, replay, as-of, provider pacing and economics are unchanged."
        )

        if run_error is None:
            if snapshot.fallback_calls != 0:
                raise RuntimeError(
                    "tailfix v1 encountered an unclassified synchronous stateful stage; "
                    "fail closed instead of applying unproven concurrency"
                )
            if snapshot.same_token_overlap_violations != 0:
                raise RuntimeError(
                    "tailfix v1 same-token cross-source overlap invariant violated"
                )
            if snapshot.pump_calls == 0 or snapshot.pumpswap_calls == 0:
                raise RuntimeError(
                    "tailfix v1 did not observe both Pump and PumpSwap stateful commit lanes"
                )


def build_parser() -> argparse.ArgumentParser:
    parser = v54.build_parser()
    parser.description = (
        "Systems-only v54 semantics with tailfix v1: separate Pump/PumpSwap stateful commit "
        "lanes plus shared per-token serialization"
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    print("Crypto Copy Trader — Route Research Systems Tailfix v1")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — frozen v54 semantics; systems scheduling change only."
    )
    asyncio.run(run_smoke_tailfix_v1(**vars(args)))


if __name__ == "__main__":
    main()
