from __future__ import annotations

import route_research_systems_stability_tailfix_v6 as v6_guard
import unified_market_route_research_smoke_tailfix_v9 as tailfix_v9


def main() -> int:
    """Run the unchanged official V6 authority with the V9 causal/audit split."""

    original_run_smoke = v6_guard.tailfix_v6.run_smoke_tailfix_v6

    async def run_v9(**kwargs):
        return await tailfix_v9.run_smoke_tailfix_v9(**kwargs)

    v6_guard.tailfix_v6.run_smoke_tailfix_v6 = run_v9
    try:
        result = int(v6_guard.main())
        print(
            "TAILFIX V9: proven continuation tickets acknowledged causally; "
            "audit work isolated from stateful ready queue"
        )
        return result
    finally:
        v6_guard.tailfix_v6.run_smoke_tailfix_v6 = original_run_smoke


if __name__ == "__main__":
    raise SystemExit(main())
