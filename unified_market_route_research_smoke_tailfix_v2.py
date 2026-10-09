from __future__ import annotations

import argparse
import asyncio

from src.pumpswap_deadline_hedged_resolver_v52 import (
    DeadlineBoundedParallelHedgedResolverV52,
)
from src.pumpswap_parallel_batched_resolver_v41 import (
    ParallelHedgedBatchedBoundedResolverV41,
)
from src.pumpswap_resolver_wait_trace_v53 import TracedDeadlineBoundedResolverV53
from src.pumpswap_shared_transport_resolver_tailfix_v2 import (
    SharedTransportDeadlineResolverTailfixV2,
)
import unified_market_latency_smoke_v19 as v19
import unified_market_route_research_smoke_tailfix_v1 as tailfix_v1
import unified_market_route_research_smoke_v53 as v53


_BASE_TAILFIX_V1_RUN_SMOKE = tailfix_v1.run_smoke_tailfix_v1


class TracedSharedTransportResolverTailfixV2(
    TracedDeadlineBoundedResolverV53,
    SharedTransportDeadlineResolverTailfixV2,
):
    """Compose v53 wait telemetry with the tailfix-v2 transport implementation.

    v53 owns the authoritative resolver substitution immediately before it invokes v52. Patching
    the v52 symbol directly is therefore overwritten by v53. Multiple inheritance keeps the v53
    observational resolve/lock/semaphore telemetry while routing `_fetch_batch` and transport
    ownership through SharedTransportDeadlineResolverTailfixV2.

    The inherited runners publish diagnostics through class-level ``last_instance`` slots on their
    own resolver classes. Because v53 and v52 replace resolver symbols dynamically, relying on MRO
    side effects alone can leave those compatibility slots unset even when the combined resolver is
    actually running. Register the same concrete instance explicitly for v41/v52/v53 and tailfix-v2
    diagnostics so the unchanged v54 guard observes the real executed resolver rather than reporting
    a false diagnostic-missing failure.
    """

    last_instance: "TracedSharedTransportResolverTailfixV2 | None" = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        TracedSharedTransportResolverTailfixV2.last_instance = self
        TracedDeadlineBoundedResolverV53.last_instance = self
        SharedTransportDeadlineResolverTailfixV2.last_instance = self
        DeadlineBoundedParallelHedgedResolverV52.last_instance = self
        ParallelHedgedBatchedBoundedResolverV41.last_instance = self


async def run_smoke_tailfix_v2(**kwargs) -> None:
    """Run tailfix v1 plus decision-time release of v52 hydration batch slots.

    Tailfix v1 keeps independent Pump/PumpSwap stateful commits off one global executor while
    preserving same-token serialization. Tailfix v2 changes only the v53-installed authoritative
    resolver implementation: endpoint calls live in one resolver-owned executor bounded by the
    already-configured max_concurrent_resolutions value, so a batch can publish its winner/deadline
    decision without retaining a v41 batch slot merely for losing-transport cleanup.
    """

    # v53, not v52, is the final resolver installation seam. It replaces v52's resolver class with
    # its TracedDeadlineBoundedResolverV53 immediately before the authoritative run. Install the
    # composed traced+tailfix class here so v53 telemetry remains present and the transport fix is
    # not overwritten before construction.
    original_traced_resolver = v53.TracedDeadlineBoundedResolverV53
    SharedTransportDeadlineResolverTailfixV2.last_instance = None
    TracedSharedTransportResolverTailfixV2.last_instance = None
    TracedDeadlineBoundedResolverV53.last_instance = None
    DeadlineBoundedParallelHedgedResolverV52.last_instance = None
    ParallelHedgedBatchedBoundedResolverV41.last_instance = None
    v53.TracedDeadlineBoundedResolverV53 = TracedSharedTransportResolverTailfixV2

    run_error: BaseException | None = None
    try:
        await _BASE_TAILFIX_V1_RUN_SMOKE(**kwargs)
    except BaseException as exc:
        run_error = exc
        raise
    finally:
        v53.TracedDeadlineBoundedResolverV53 = original_traced_resolver
        resolver = SharedTransportDeadlineResolverTailfixV2.last_instance
        print("\nTAILFIX V2 SHARED RPC TRANSPORT / DECISION RELEASE DIAGNOSTIC")
        if resolver is None:
            print("tailfix_v2_resolver_instance=missing")
            if run_error is None:
                raise RuntimeError("tailfix v2 traced resolver was not installed")
            return

        snapshot = resolver.tailfix_snapshot_v2()
        print(
            f"transport_workers={snapshot.transport_workers} "
            f"max_active_transports={snapshot.max_active_transports} "
            f"active_transports_after_run={snapshot.active_transports} "
            f"transport_limit_violations={snapshot.transport_limit_violations} "
            f"decisions_released={snapshot.decisions_released} "
            f"residual_cleanup_pending={snapshot.residual_cleanup_pending} "
            f"residual_cleanup_high_water={snapshot.residual_cleanup_high_water}"
        )
        print(
            "tailfix_v2_decision_release_ms "
            f"{v19._latency_summary_ms(list(snapshot.decision_release_seconds))}"
        )
        print(
            "tailfix_v2_residual_cleanup_ms "
            f"{v19._latency_summary_ms(list(snapshot.residual_cleanup_seconds))}"
        )
        print(
            "tailfix_v2_note=v53 resolver wait telemetry is preserved while hedge decision "
            "availability releases the v41 batch slot immediately. Already-running loser "
            "transports drain only inside one shared executor whose worker count equals the "
            "inherited max_concurrent_resolutions ceiling; queued losers are cancelled. Cache, "
            "per-pool single-flight, hydration budget, as-of, reservation FIFO, detector, provider "
            "pacing and economics remain unchanged."
        )

        if run_error is None:
            if snapshot.transport_limit_violations != 0:
                raise RuntimeError("tailfix v2 exceeded the frozen RPC transport ceiling")
            if snapshot.max_active_transports > snapshot.transport_workers:
                raise RuntimeError("tailfix v2 observed hidden RPC oversubscription")
            if snapshot.decisions_released <= 0:
                raise RuntimeError("tailfix v2 did not observe any hedged hydration decisions")


def build_parser() -> argparse.ArgumentParser:
    parser = tailfix_v1.build_parser()
    parser.description = (
        "Systems-only tailfix v2: tailfix v1 commit lanes plus bounded shared RPC transport "
        "executor with hydration batch release at hedge decision time"
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    print("Crypto Copy Trader — Route Research Systems Tailfix v2")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — frozen v54 gate and economics; systems transport "
        "scheduling change only."
    )
    asyncio.run(run_smoke_tailfix_v2(**vars(args)))


if __name__ == "__main__":
    main()
