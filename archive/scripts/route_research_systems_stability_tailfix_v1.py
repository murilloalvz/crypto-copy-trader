from __future__ import annotations

import route_research_systems_stability_v54 as v54_guard
import unified_market_route_research_smoke_tailfix_v1 as tailfix


def main() -> int:
    """Run the existing v54 systems-only guard through tailfix v1.

    `route_research_systems_stability_v54` remains the authority for the unchanged
    11/11 gate and for blocking forward economics. This wrapper changes only the smoke
    implementation injected into the frozen v43/v44 acquisition harness.
    """

    original_run_smoke = v54_guard.v54.run_smoke_v54
    v54_guard.v54.run_smoke_v54 = tailfix.run_smoke_tailfix_v1
    try:
        result = int(v54_guard.main())
    finally:
        v54_guard.v54.run_smoke_v54 = original_run_smoke

    print("\nTAILFIX V1 SYSTEMS STABILITY WRAPPER")
    print(
        "classification="
        + (
            "PASS_TAILFIX_V1_UNCHANGED_11_GATE"
            if result == 0
            else "FAIL_TAILFIX_V1_UNCHANGED_11_GATE"
        )
    )
    print(
        "Interpretation: this runner validates scheduling capacity only. It cannot validate "
        "Flow60 buy-share economics, fills, realized PnL or live-money readiness."
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
