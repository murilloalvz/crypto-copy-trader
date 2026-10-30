from __future__ import annotations

import route_research_prospective_flow60_buy_share_holdout_v68 as v68
import unified_market_route_research_smoke_tailfix_v2 as tailfix_v2


TAILFIX_V2_SYSTEMS_PROFILE = "v54_demand_only_resolution+tailfix_v1_commit_lanes+tailfix_v2_shared_rpc_transport"


def main() -> int:
    """Run the frozen v68 economic protocol on the validated tailfix-v2 systems path.

    This wrapper changes only the systems implementation injected at v68's existing v54 seam.
    Feature definition, bins, favorable direction, 900s primary horizon, provider pacing,
    v46 A/B cohort semantics, route notional/slippage, causal feature builder, support gate and
    PASS/FAIL/INCONCLUSIVE evaluator remain owned by the unchanged v68 module.
    """

    original_run_smoke = v68.v54.run_smoke_v54
    original_profile = v68.V68_VALIDATED_SYSTEMS_PROFILE
    v68.v54.run_smoke_v54 = tailfix_v2.run_smoke_tailfix_v2
    v68.V68_VALIDATED_SYSTEMS_PROFILE = TAILFIX_V2_SYSTEMS_PROFILE
    try:
        return int(v68.main())
    finally:
        v68.v54.run_smoke_v54 = original_run_smoke
        v68.V68_VALIDATED_SYSTEMS_PROFILE = original_profile


if __name__ == "__main__":
    raise SystemExit(main())
