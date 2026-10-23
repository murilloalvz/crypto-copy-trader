from __future__ import annotations

from contextlib import contextmanager
import math
from typing import Any, Iterator, Mapping

from src.causal_quotes import CausalQuoteObservation

FIX_VERSION = "launch_burst_price_impact_semantics_fix_v0"
JUPITER_SWAP_V2_DOC = "https://dev.jup.ag/api-reference/swap/order"


def route_quality_quote(
    quote: CausalQuoteObservation,
    contract: Mapping[str, Any],
) -> tuple[bool, str]:
    """Apply the frozen upper-bound route-quality contract to Swap V2 priceImpact.

    Jupiter Swap V2 documents ``priceImpact`` in percentage points and explicitly permits
    negative values (for example, -0.1 means -0.1%). The frozen Launch Burst contract only
    requires a finite provider value and caps it above at 2 percentage points; it does not
    impose a non-negative lower bound.
    """

    impact = quote.provider_price_impact_pct_points
    if impact is None:
        return False, "PRICE_IMPACT_UNAVAILABLE"
    try:
        value = float(impact)
    except (TypeError, ValueError):
        return False, "PRICE_IMPACT_UNAVAILABLE"
    if not math.isfinite(value):
        return False, "PRICE_IMPACT_UNAVAILABLE"
    if value > float(contract["route_quality"]["max_provider_price_impact_pct_points"]):
        return False, "PRICE_IMPACT_EXCEEDS_LIMIT"
    return True, "OK"


def route_quality_mapping(quote: Mapping[str, Any], contract: Mapping[str, Any]) -> bool:
    impact = quote.get("provider_price_impact_pct_points")
    if impact is None:
        return False
    try:
        value = float(impact)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value <= float(
        contract["route_quality"]["max_provider_price_impact_pct_points"]
    )


@contextmanager
def patched_price_impact_semantics() -> Iterator[None]:
    """Patch only the replay/economic evaluator call sites, then restore them.

    The historical V2 implementation is intentionally left unchanged on disk so previously
    generated artifacts remain reproducible. This context manager versions the implementation
    correction explicitly for new replays/runs without mutating the frozen route contract.
    """

    from src import launch_burst_route_paper_v2 as route_paper
    from benchmarks.launch_burst_control_taker_sim_v0 import smart_ladder_25

    original_route = route_paper._route_quality_ok
    original_smart = smart_ladder_25._route_quality_ok
    route_paper._route_quality_ok = route_quality_quote
    smart_ladder_25._route_quality_ok = route_quality_mapping
    try:
        yield
    finally:
        route_paper._route_quality_ok = original_route
        smart_ladder_25._route_quality_ok = original_smart
