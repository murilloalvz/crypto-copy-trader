from __future__ import annotations

import route_research_systems_stability_tailfix_v6 as v6_guard
import unified_market_route_research_smoke_tailfix_v8 as tailfix_v8


def main() -> int:
    """Run the unchanged official V6 authority with the V8 writer correction."""

    original_run_smoke = v6_guard.tailfix_v6.run_smoke_tailfix_v6

    async def run_v8(**kwargs):
        return await tailfix_v8.run_smoke_tailfix_v8(**kwargs)

    v6_guard.tailfix_v6.run_smoke_tailfix_v6 = run_v8
    try:
        result = int(v6_guard.main())
        print("TAILFIX V8: authoritative writer causal admission + canonical readback batching active")
        return result
    finally:
        v6_guard.tailfix_v6.run_smoke_tailfix_v6 = original_run_smoke


if __name__ == "__main__":
    raise SystemExit(main())
