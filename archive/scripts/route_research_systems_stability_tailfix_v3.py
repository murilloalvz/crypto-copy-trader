from __future__ import annotations

import route_research_systems_stability_v54 as v54_guard
import unified_market_route_research_smoke_tailfix_v3 as tailfix


V3_HEADROOM_HOLD_EXIT = 2


def main() -> int:
    """Run frozen 11/11 authority, then apply a stricter non-economic promotion hold."""

    original_run_smoke = v54_guard.v54.run_smoke_v54
    v54_guard.v54.run_smoke_v54 = tailfix.run_smoke_tailfix_v3
    try:
        systems_result = int(v54_guard.main())
    finally:
        v54_guard.v54.run_smoke_v54 = original_run_smoke

    report = tailfix.last_headroom_report_v3
    missing_headroom = systems_result == 0 and report is None
    warning_stages = tuple(report.warning_stages) if report is not None else ()
    promotion_hold = systems_result == 0 and (missing_headroom or bool(warning_stages))

    if systems_result != 0:
        result = systems_result
        classification = "FAIL_TAILFIX_V3_UNCHANGED_11_GATE"
    elif promotion_hold:
        result = V3_HEADROOM_HOLD_EXIT
        classification = "HOLD_TAILFIX_V3_LATENCY_HEADROOM"
    else:
        result = 0
        classification = "PASS_TAILFIX_V3_11_GATE_WITH_HEADROOM"

    print("\nTAILFIX V3 SYSTEMS STABILITY WRAPPER")
    print(f"systems_11_of_11_pass={systems_result == 0}")
    print(f"headroom_report_present={report is not None}")
    print(
        "headroom_warning_stages="
        + (",".join(warning_stages) if warning_stages else "none")
    )
    print(f"classification={classification}")
    print(
        "Interpretation: the official 11/11 systems gate and 5s p95 limits are unchanged. V3 adds "
        "a stricter promotion-only hold: even an official PASS does not unlock another V68 economic "
        "run when one causal stage already consumes >=80% of the 5s budget, or when the headroom "
        "report is missing. This is preventive systems policy, not an economic criterion."
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
