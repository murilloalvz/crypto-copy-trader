from __future__ import annotations

import route_research_systems_stability_v54 as v54_guard
import unified_market_route_research_smoke_tailfix_v3 as tailfix_v3
import unified_market_route_research_smoke_tailfix_v5 as tailfix_v5


V5_PROMOTION_HOLD_EXIT = 2


def main() -> int:
    """Run the frozen 11/11 authority, then require latency and sustained-throughput headroom."""

    original_run_smoke = v54_guard.v54.run_smoke_v54
    v54_guard.v54.run_smoke_v54 = tailfix_v5.run_smoke_tailfix_v5
    try:
        systems_result = int(v54_guard.main())
    finally:
        v54_guard.v54.run_smoke_v54 = original_run_smoke

    latency_report = tailfix_v3.last_headroom_report_v3
    latency_warnings = tuple(latency_report.warning_stages) if latency_report is not None else ()
    writer_report = tailfix_v5.last_writer_headroom_v5
    resolver_report = tailfix_v5.last_resolver_snapshot_v5
    resolver_v3_report = tailfix_v5.last_resolver_v3_snapshot_v5
    writer_warning = bool(tailfix_v5.last_writer_warning_v5)

    missing_preventive_evidence = systems_result == 0 and (
        latency_report is None
        or writer_report is None
        or resolver_report is None
        or resolver_v3_report is None
    )
    promotion_hold = systems_result == 0 and (
        missing_preventive_evidence or bool(latency_warnings) or writer_warning
    )

    if systems_result != 0:
        result = systems_result
        classification = "FAIL_TAILFIX_V5_UNCHANGED_11_GATE"
    elif promotion_hold:
        result = V5_PROMOTION_HOLD_EXIT
        classification = "HOLD_TAILFIX_V5_PREVENTIVE_HEADROOM"
    else:
        result = 0
        classification = "PASS_TAILFIX_V5_11_GATE_WITH_CAUSAL_AND_THROUGHPUT_HEADROOM"

    print("\nTAILFIX V5 SYSTEMS STABILITY WRAPPER")
    print(f"systems_11_of_11_pass={systems_result == 0}")
    print(f"latency_headroom_report_present={latency_report is not None}")
    print(
        "latency_headroom_warning_stages="
        + (",".join(latency_warnings) if latency_warnings else "none")
    )
    print(f"resolver_preventive_report_present={resolver_report is not None}")
    if resolver_report is not None:
        print(
            f"historical_promotions={resolver_report.normalization_historical_promotions} "
            f"network_resolutions={resolver_report.normalization_network_resolutions} "
            f"delayed_availability_reuses={resolver_report.delayed_availability_reuses} "
            f"coalesced_after_pool_lock_reuses={resolver_report.coalesced_after_pool_lock_reuses}"
        )
    print(f"writer_headroom_report_present={writer_report is not None}")
    print(f"writer_sustained_pressure_warning={writer_warning}")
    print(
        f"writer_queue_p95_pressure_share_pct={tailfix_v5.last_writer_queue_p95_share_v5 * 100.0:.1f}"
    )
    if writer_report is not None:
        print(
            f"writer_result_wait_p95_ms={writer_report.result_wait_p95_seconds * 1000.0:.1f} "
            f"writer_pending_at_close={writer_report.base.pending_at_close}"
        )
    print(f"classification={classification}")
    print(
        "Interpretation: the frozen v43 11/11 gate and 5s p95 limit remain authoritative. V5 "
        "requires the v3 stage headroom plus resolver/coalescing evidence and sustained writer p95 "
        "headroom. V4's single maximum queue spike remains diagnostic only; promotion is blocked by "
        "sustained p95 pressure, >=4s writer result wait, incomplete drain, missing preventive "
        "evidence or any v3 latency warning. No V68 economics may start on FAIL or HOLD."
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
