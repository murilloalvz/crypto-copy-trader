from __future__ import annotations

import route_research_systems_stability_tailfix_v6 as v6_guard
import unified_market_route_research_smoke_tailfix_v7 as tailfix_v7


def main() -> int:
    """Run the unchanged V6 authority with observation-only HOL attribution."""

    original_run_smoke = v6_guard.tailfix_v6.run_smoke_tailfix_v6
    v6_guard.tailfix_v6.run_smoke_tailfix_v6 = tailfix_v7.run_smoke_tailfix_v7
    try:
        return int(v6_guard.main())
    finally:
        v6_guard.tailfix_v6.run_smoke_tailfix_v6 = original_run_smoke


if __name__ == "__main__":
    raise SystemExit(main())
