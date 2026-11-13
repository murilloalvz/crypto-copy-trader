from __future__ import annotations

import route_research_prospective_flow60_buy_share_holdout_v68 as v68
import unified_market_route_research_smoke_tailfix_v9 as tailfix_v9


TAILFIX_V9_SYSTEMS_PROFILE = (
    "v9_v6_partial_order+v8_causal_authoritative_writer+v9_demoted_audit_split"
)


def main() -> int:
    """Run the frozen V68 protocol through the accepted V9 systems path.

    This is plumbing-only: the unchanged V68 module still owns acquisition, feature
    construction, route-only economics, causal audit, support and PASS/FAIL gates.
    """

    original_run_smoke = v68.v54.run_smoke_v54
    original_profile = v68.V68_VALIDATED_SYSTEMS_PROFILE
    v68.v54.run_smoke_v54 = tailfix_v9.run_smoke_tailfix_v9
    v68.V68_VALIDATED_SYSTEMS_PROFILE = TAILFIX_V9_SYSTEMS_PROFILE
    try:
        return int(v68.main())
    finally:
        v68.v54.run_smoke_v54 = original_run_smoke
        v68.V68_VALIDATED_SYSTEMS_PROFILE = original_profile


if __name__ == "__main__":
    raise SystemExit(main())
