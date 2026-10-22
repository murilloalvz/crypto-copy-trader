from __future__ import annotations

import route_research_systems_stability_tailfix_v5 as v5_guard
import unified_market_route_research_smoke_tailfix_v6 as tailfix_v6


V6_PROMOTION_HOLD_EXIT = 2


def main() -> int:
    """Run the unchanged 11/11 authority plus V5 headroom and V6 graph evidence."""

    original_run_smoke = v5_guard.v54_guard.v54.run_smoke_v54
    v5_guard.v54_guard.v54.run_smoke_v54 = tailfix_v6.run_smoke_tailfix_v6
    try:
        systems_result = int(v5_guard.v54_guard.main())
    finally:
        v5_guard.v54_guard.v54.run_smoke_v54 = original_run_smoke

    coordinator = tailfix_v6.v19.last_pumpswap_partial_order_coordinator_v6
    graph_ok = coordinator is not None
    graph_snapshot = coordinator.snapshot() if coordinator is not None else None
    latency_report = tailfix_v6.tailfix_v5.tailfix_v3.last_headroom_report_v3
    latency_warnings = (
        tuple(latency_report.warning_stages) if latency_report is not None else ()
    )
    writer_report = tailfix_v6.tailfix_v5.last_writer_headroom_v5
    resolver_report = tailfix_v6.tailfix_v5.last_resolver_snapshot_v5
    resolver_v3_report = tailfix_v6.tailfix_v5.last_resolver_v3_snapshot_v5
    writer_warning = bool(tailfix_v6.tailfix_v5.last_writer_warning_v5)
    missing_preventive_evidence = systems_result == 0 and (
        latency_report is None
        or writer_report is None
        or resolver_report is None
        or resolver_v3_report is None
    )
    promotion_hold = systems_result == 0 and (
        missing_preventive_evidence or bool(latency_warnings) or writer_warning or not graph_ok
    )

    if systems_result != 0:
        result = systems_result
        classification = "FAIL_TAILFIX_V6_UNCHANGED_11_GATE"
    elif promotion_hold:
        result = V6_PROMOTION_HOLD_EXIT
        classification = "HOLD_TAILFIX_V6_PREVENTIVE_HEADROOM"
    else:
        result = 0
        classification = "PASS_TAILFIX_V6_11_GATE_WITH_CAUSAL_PARTIAL_ORDER"

    print("\nTAILFIX V6 SYSTEMS STABILITY WRAPPER")
    print(f"systems_11_of_11_pass={systems_result == 0}")
    print(f"latency_headroom_report_present={latency_report is not None}")
    print(
        "latency_headroom_warning_stages="
        + (",".join(latency_warnings) if latency_warnings else "none")
    )
    print(f"writer_headroom_report_present={writer_report is not None}")
    print(f"writer_sustained_pressure_warning={writer_warning}")
    print(f"partial_order_evidence_present={graph_ok}")
    if graph_snapshot is not None:
        print(
            f"partial_order_admissions={graph_snapshot.admissions} "
            f"partial_order_dependency_edges={graph_snapshot.dependency_edges} "
            f"partial_order_disjoint_admissions={graph_snapshot.disjoint_admissions} "
            f"partial_order_overlapping_admissions={graph_snapshot.overlapping_admissions} "
            f"partial_order_out_of_ingress_admissions={graph_snapshot.out_of_ingress_admissions}"
        )
    print(f"classification={classification}")
    print(
        "Interpretation: the official 11/11 gate, 5s p95 gate, V5 normalization/headroom policy, "
        "RPC ceiling, one physical SQLite writer and economics remain unchanged. V6 only removes "
        "cross-asset reservation HOL after causal normalization and requires graph evidence."
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
