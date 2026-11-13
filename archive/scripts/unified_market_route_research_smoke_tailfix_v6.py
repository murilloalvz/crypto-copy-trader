from __future__ import annotations

import unified_market_route_research_smoke_tailfix_v5 as tailfix_v5
import unified_market_latency_smoke_v19 as v19


async def run_smoke_tailfix_v6(**kwargs) -> None:
    """Run V5 with causal per-asset admission instead of the global prefix barrier."""

    run_kwargs = dict(kwargs)
    requested = run_kwargs.get("pumpswap_reservation_mode")
    if requested not in (None, "partial_order"):
        raise ValueError("Tailfix v6 requires pumpswap_reservation_mode=partial_order")
    run_kwargs["pumpswap_reservation_mode"] = "partial_order"
    await tailfix_v5.run_smoke_tailfix_v5(**run_kwargs)

    coordinator = v19.last_pumpswap_partial_order_coordinator_v6
    print("\nTAILFIX V6 CAUSAL PARTIAL-ORDER DIAGNOSTIC")
    if coordinator is None:
        raise RuntimeError("tailfix v6 partial-order coordinator was not installed")
    snapshot = coordinator.snapshot()
    print(
        f"partial_order_admissions={snapshot.admissions} "
        f"dependency_edges={snapshot.dependency_edges} "
        f"disjoint_admissions={snapshot.disjoint_admissions} "
        f"overlapping_admissions={snapshot.overlapping_admissions} "
        f"out_of_ingress_admissions={snapshot.out_of_ingress_admissions} "
        f"max_predecessors={snapshot.max_predecessors_per_admission}"
    )
    print(
        "tailfix_v6_note=the global normalization prefix is removed only from reservation admission. "
        "Each asset keeps a causal ticket chain; disjoint assets have no dependency edge. The "
        "writer remains asynchronous and authoritative, the canonical-result superset guard stays "
        "fail-closed, and the stateful/demoted ready queue remains unchanged."
    )


def build_parser():
    parser = tailfix_v5.build_parser()
    parser.description = (
        "Systems-only Tailfix v6: V5 normalization plus causal per-asset partial-order admission"
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    import asyncio

    print("Crypto Copy Trader — Route Research Systems Tailfix v6")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — partial-order causal scheduling only; "
        "detector, RPC ceiling, SQLite writer count, gate and economics frozen."
    )
    asyncio.run(run_smoke_tailfix_v6(**vars(args)))


if __name__ == "__main__":
    main()
