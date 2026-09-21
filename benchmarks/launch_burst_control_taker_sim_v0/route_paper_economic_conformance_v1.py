from __future__ import annotations

from typing import Any

from benchmarks.launch_burst_control_taker_sim_v0.price_impact_semantics_fix_v0 import (
    FIX_VERSION,
    JUPITER_SWAP_V2_DOC,
    patched_price_impact_semantics,
    route_quality_mapping,
    route_quality_quote,
)
from benchmarks.launch_burst_control_taker_sim_v0.run_v4_smart_ladder_25 import (
    run_sim_v4 as _historical_run_sim_v4,
)


CONFORMANCE_VERSION = "route_paper_economic_conformance_v1"


def assert_price_impact_semantics_active() -> dict[str, Any]:
    from src import launch_burst_route_paper_v2 as route_paper
    from benchmarks.launch_burst_control_taker_sim_v0 import smart_ladder_25

    if route_paper._route_quality_ok is not route_quality_quote:
        raise RuntimeError(
            "economic route conformance failed: corrected Swap V2 priceImpact "
            "semantics are not active for fixed +60 route-paper"
        )
    if smart_ladder_25._route_quality_ok is not route_quality_mapping:
        raise RuntimeError(
            "economic route conformance failed: corrected Swap V2 priceImpact "
            "semantics are not active for Smart-Ladder route-paper"
        )

    return {
        "conformance_version": CONFORMANCE_VERSION,
        "price_impact_semantics_fix_version": FIX_VERSION,
        "jupiter_swap_v2_documentation": JUPITER_SWAP_V2_DOC,
        "negative_finite_price_impact_is_available": True,
        "missing_or_nonfinite_price_impact_is_unavailable": True,
        "frozen_upper_bound_remains_authoritative": True,
    }


async def run_sim_v4_conformant(**kwargs: Any) -> dict[str, Any]:
    """Run the historical V4 simulator under mandatory current economic conformance.

    The historical runner is intentionally left unchanged for artifact reproducibility.
    All new economic experiments should call this wrapper instead of the raw runner.
    """

    with patched_price_impact_semantics():
        attestation = assert_price_impact_semantics_active()
        report = await _historical_run_sim_v4(**kwargs)

    guardrails = dict(report.get("guardrails") or {})
    guardrails.update(
        {
            "route_paper_economic_conformance_version": CONFORMANCE_VERSION,
            "price_impact_semantics_fix_applied": True,
            "raw_historical_runner_called_without_fix": False,
        }
    )
    report["guardrails"] = guardrails
    report["route_paper_economic_conformance"] = attestation
    return report
