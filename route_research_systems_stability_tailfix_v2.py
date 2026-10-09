from __future__ import annotations

import route_research_systems_stability_v54 as v54_guard
import unified_market_route_research_smoke_tailfix_v2 as tailfix


def main() -> int:
    """Run the frozen v54 systems-only guard through tailfix v2."""

    original_run_smoke = v54_guard.v54.run_smoke_v54
    v54_guard.v54.run_smoke_v54 = tailfix.run_smoke_tailfix_v2
    try:
        result = int(v54_guard.main())
    finally:
        v54_guard.v54.run_smoke_v54 = original_run_smoke

    print("\nTAILFIX V2 SYSTEMS STABILITY WRAPPER")
    print(
        "classification="
        + (
            "PASS_TAILFIX_V2_UNCHANGED_11_GATE"
            if result == 0
            else "FAIL_TAILFIX_V2_UNCHANGED_11_GATE"
        )
    )
    print(
        "Interpretation: this runner validates systems scheduling only. It cannot validate "
        "Flow60 buy-share economics, fills, realized PnL or live-money readiness."
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
