from __future__ import annotations

import route_research_systems_stability_v54 as v54_guard
import unified_market_route_research_smoke_tailfix_v3 as tailfix_v3
import unified_market_route_research_smoke_tailfix_v4 as tailfix_v4


V4_PROMOTION_HOLD_EXIT = 2


def main() -> int:
    """Run frozen 11/11 authority, then require latency and writer-pressure headroom."""

    original_run_smoke = v54_guard.v54.run_smoke_v54
    v54_guard.v54.run_smoke_v54 = tailfix_v4.run_smoke_tailfix_v4
    try:
        systems_result = int(v54_guard.main())
    finally:
        v54_guard.v54.run_smoke_v54 = original_run_smoke

    latency_report = tailfix_v3.last_headroom_report_v3
    latency_warnings = tuple(latency_report.warning_stages) if latency_report is not None else ()
    writer_report = tailfix_v4.last_writer_pressure_v4
    writer_warning = bool(tailfix_v4.last_writer_pressure_warning_v4)

    missing_preventive_evidence = systems_result == 0 and (
        latency_report is None or writer_report is None
    )
    promotion_hold = systems_result == 0 and (
        missing_preventive_evidence or bool(latency_warnings) or writer_warning
    )

    if systems_result != 0:
        result = systems_result
        classification = "FAIL_TAILFIX_V4_UNCHANGED_11_GATE"
    elif promotion_hold:
        result = V4_PROMOTION_HOLD_EXIT
        classification = "HOLD_TAILFIX_V4_PREVENTIVE_HEADROOM"
    else:
        result = 0
        classification = "PASS_TAILFIX_V4_11_GATE_WITH_LATENCY_AND_THROUGHPUT_HEADROOM"

    print("\nTAILFIX V4 SYSTEMS STABILITY WRAPPER")
    print(f"systems_11_of_11_pass={systems_result == 0}")
    print(f"latency_headroom_report_present={latency_report is not None}")
    print(
        "latency_headroom_warning_stages="
        + (",".join(latency_warnings) if latency_warnings else "none")
    )
    print(f"writer_pressure_report_present={writer_report is not None}")
    print(f"writer_pressure_warning={writer_warning}")
    print(
        f"writer_queue_pressure_share_pct={tailfix_v4.last_writer_pressure_share_v4 * 100.0:.1f}"
    )
    print(f"classification={classification}")
    print(
        "Interpretation: the official v43 11/11 systems gate is unchanged. V4 adds only a stricter "
        "promotion hold: a systems PASS still cannot unlock V68 if a latency stage consumes >=80% "
        "of the 5s budget or the PumpSwap writer queue consumes >=80% of the bounded persistence "
        "worker reservoir. This protects the next economic sample from near-saturation."
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
