from __future__ import annotations

import route_research_systems_stability_v54 as v54_guard
import unified_market_route_research_smoke_tailfix_v3 as tailfix


def main() -> int:
    """Run the frozen v54 11/11 systems authority through preventive Tailfix v3."""

    original_run_smoke = v54_guard.v54.run_smoke_v54
    v54_guard.v54.run_smoke_v54 = tailfix.run_smoke_tailfix_v3
    try:
        result = int(v54_guard.main())
    finally:
        v54_guard.v54.run_smoke_v54 = original_run_smoke

    print("\nTAILFIX V3 SYSTEMS STABILITY WRAPPER")
    print(
        "classification="
        + (
            "PASS_TAILFIX_V3_UNCHANGED_11_GATE"
            if result == 0
            else "FAIL_TAILFIX_V3_UNCHANGED_11_GATE"
        )
    )
    print(
        "Interpretation: V3 hardens and observes systems latency only. The official 11/11 gate and "
        "5s p95 thresholds are unchanged. No Flow60 buy-share economics, fill realism, realized "
        "PnL or live-money readiness is evaluated here."
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
