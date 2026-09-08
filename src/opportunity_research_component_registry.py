from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchComponentSpec:
    key: str
    source_tracks: tuple[str, ...]
    phase: str
    chain_scope: str
    preentry_selection_eligible: bool
    role: str
    causal_boundary: str


COMPONENT_SPECS: tuple[ResearchComponentSpec, ...] = (
    ResearchComponentSpec(
        key="movement_intensity_direction",
        source_tracks=("radar", "v55", "v68"),
        phase="pre_entry",
        chain_scope="solana_current",
        preentry_selection_eligible=True,
        role="movement, activity intensity, acceleration and buy/sell composition",
        causal_boundary="detector remains frozen; evidence must be known by research decision",
    ),
    ResearchComponentSpec(
        key="participant_distribution",
        source_tracks=("participant_distribution_research",),
        phase="pre_entry",
        chain_scope="shared_concept_chain_specific_observations",
        preentry_selection_eligible=True,
        role="breadth, event concentration and repetition among observed participant addresses",
        causal_boundary=(
            "T0-anchored market window plus knowledge cutoff; incomplete identity keeps structural "
            "metrics missing"
        ),
    ),
    ResearchComponentSpec(
        key="temporal_flow_structure",
        source_tracks=("temporal_flow_structure_research",),
        phase="pre_entry",
        chain_scope="shared_concept_chain_specific_observations",
        preentry_selection_eligible=True,
        role="persistence versus burstiness across fixed market-time subwindows",
        causal_boundary="market clock anchored to T0; observed_at must be known by decision",
    ),
    ResearchComponentSpec(
        key="wallet_convergence",
        source_tracks=("v60", "v65"),
        phase="pre_entry",
        chain_scope="chain_aware",
        preentry_selection_eligible=True,
        role="participation by a deterministic pre-frozen useful-wallet cohort",
        causal_boundary=(
            "cohort member frozen strictly before episode T0; market participation T0-anchored; "
            "wallet evidence never drives acquisition"
        ),
    ),
    ResearchComponentSpec(
        key="token_hazard_integrity",
        source_tracks=("hazard",),
        phase="pre_entry",
        chain_scope="provider_and_chain_specific",
        preentry_selection_eligible=True,
        role="causal token/program/authority/provider-native risk evidence",
        causal_boundary="provider-native semantics remain separate and missingness stays explicit",
    ),
    ResearchComponentSpec(
        key="direct_funding_relationship",
        source_tracks=("v61",),
        phase="pre_entry_relationship_research",
        chain_scope="chain_specific",
        preentry_selection_eligible=False,
        role="exact causal direct deployer/participant transfer relationship",
        causal_boundary=(
            "direct link does not prove common ownership, insider status, manipulation or wash; "
            "requires a separate protocol before entering selection"
        ),
    ),
    ResearchComponentSpec(
        key="social_evidence",
        source_tracks=("v57",),
        phase="pre_entry_optional",
        chain_scope="exact_token_identity",
        preentry_selection_eligible=False,
        role="causal exact-token social observations and engagement snapshots",
        causal_boundary="created_at is not availability; no approved live provider yet",
    ),
    ResearchComponentSpec(
        key="exceptional_trade_preentry",
        source_tracks=("v56", "v63"),
        phase="discovery_support",
        chain_scope="reference_trade_specific",
        preentry_selection_eligible=False,
        role="outcome-blind pre-entry evidence and matched controls for exceptional-trade research",
        causal_boundary=(
            "feature evidence must be strictly before reference entry; outcome/control labels are "
            "joined only after feature construction"
        ),
    ),
    ResearchComponentSpec(
        key="pons_lifecycle_progress",
        source_tracks=("v62", "v64", "v66"),
        phase="pre_entry_chain_specific",
        chain_scope="robinhood_chain_pons",
        preentry_selection_eligible=False,
        role="Pons lifecycle, exact curve progress and deployed capability authority",
        causal_boundary=(
            "chain/protocol-specific raw semantics; no Solana threshold reuse and deployed "
            "capabilities require authoritative attestation"
        ),
    ),
    ResearchComponentSpec(
        key="pons_launch_quality",
        source_tracks=("v67",),
        phase="pre_entry_chain_specific",
        chain_scope="robinhood_chain_pons",
        preentry_selection_eligible=False,
        role="raw causal launch/deployer/social/early-flow evidence without weighted score",
        causal_boundary="raw evidence only; no FIRE/WATCH/SKIP weights without validation",
    ),
    ResearchComponentSpec(
        key="route_executability",
        source_tracks=("route_research", "executable_buy"),
        phase="execution_gate",
        chain_scope="provider_specific",
        preentry_selection_eligible=False,
        role="route, assembly, landing and fill realism between selection and shadow",
        causal_boundary="route available != assemblable transaction != landed transaction != fill",
    ),
    ResearchComponentSpec(
        key="market_first_exit_geometry",
        source_tracks=("v58",),
        phase="post_entry",
        chain_scope="route_path_specific",
        preentry_selection_eligible=False,
        role="MFE, MAE, timing, giveback, MFE capture, coverage and gaps after entry",
        causal_boundary="post-entry path geometry is forbidden in same-episode pre-entry selection",
    ),
    ResearchComponentSpec(
        key="shadow_execution",
        source_tracks=("future_shadow",),
        phase="post_selection_execution",
        chain_scope="execution_environment_specific",
        preentry_selection_eligible=False,
        role="realistic non-funded execution behavior before live capital",
        causal_boundary="requires prospective selection plus execution and exit evidence first",
    ),
    ResearchComponentSpec(
        key="position_sizing",
        source_tracks=("future_sizing",),
        phase="post_shadow",
        chain_scope="portfolio_level",
        preentry_selection_eligible=False,
        role="capital allocation using validated net-return and risk distributions",
        causal_boundary="must not optimize capital before edge/execution/exit/shadow are established",
    ),
)


_COMPONENT_BY_KEY = {item.key: item for item in COMPONENT_SPECS}
if len(_COMPONENT_BY_KEY) != len(COMPONENT_SPECS):
    raise RuntimeError("duplicate research component key")


def get_research_component_spec(key: str) -> ResearchComponentSpec:
    try:
        return _COMPONENT_BY_KEY[key]
    except KeyError as exc:
        raise ValueError(f"unknown research component: {key}") from exc


def assert_components_allowed_in_preentry_selection(component_keys: tuple[str, ...]) -> None:
    """Reject downstream/unapproved families from a future pre-entry selection protocol."""

    seen: set[str] = set()
    for key in component_keys:
        if key in seen:
            raise ValueError(f"duplicate research component: {key}")
        seen.add(key)
        spec = get_research_component_spec(key)
        if not spec.preentry_selection_eligible:
            raise ValueError(
                f"research component {key} is not approved for pre-entry selection: "
                f"phase={spec.phase}"
            )
