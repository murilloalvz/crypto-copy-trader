from __future__ import annotations

from dataclasses import asdict, dataclass


VERSION = "opportunity_research_alignment_v1"


@dataclass(frozen=True)
class ResearchStageV1:
    stage_id: str
    dimension: str
    plane: str
    role: str
    evidence_source: str
    status: str


DECISION_DIMENSIONS_V1 = (
    "manipulation_risk",
    "organic_demand",
    "opportunity_alpha",
    "copyability_execution",
    "wallet_intelligence",
)

TRACKS_V1 = {
    "market_first": "INDEPENDENT_PRIMARY_RESEARCH_TRACK",
    "social_event_first": "INDEPENDENT_PRIMARY_RESEARCH_TRACK",
    "convergence": "BLOCKED_UNTIL_INDEPENDENT_EVIDENCE_SUPPORTS_IT",
}

EXTERNAL_RESEARCH_PLACEMENT_V1 = {
    "gmgn_wallet_and_token_labels": "RESEARCH_PLANE_LABELS_ONLY_UNTIL_CAUSAL_AVAILABILITY_IS_PROVEN",
    "solana_tracker_wallet_labels": "RESEARCH_PLANE_LABELS_ONLY_UNTIL_CAUSAL_AVAILABILITY_IS_PROVEN",
    "jupiter_organic_score": "FOLLOWUP_RESEARCH_LABEL_NOT_5S_LAUNCH_SELECTOR",
    "melt_entity_clustering_ideas": "FEATURE_DESIGN_REFERENCE_REIMPLEMENT_FROM_CAUSAL_EVIDENCE",
}

SOLANA_PLAN_V1 = (
    ResearchStageV1(
        "sol_routeable_edge_discovery_v2",
        "opportunity_alpha",
        "research",
        "Separate alpha from provider availability by analyzing only Fixed+60 route-usable entries.",
        "existing_frozen_capture_and_route_shadow",
        "READY_TO_RUN_OFFLINE",
    ),
    ResearchStageV1(
        "sol_coordination_organicity_discovery_v0",
        "manipulation_risk",
        "research",
        "Replace wallet-count assumptions with entity-adjusted breadth/concentration, early-buyer retention, sell pressure and coordination proxies.",
        "causal_5s_event_graph_plus_preserved_identity_evidence",
        "NEXT_IMPLEMENTATION_PRIORITY",
    ),
    ResearchStageV1(
        "sol_wallet_intelligence_v0",
        "wallet_intelligence",
        "research",
        "Score prior-only trader history separately from whether a trade is copyable.",
        "prior_wallet_history_only_external_labels_may_bootstrap_research",
        "PLANNED_RESEARCH_PLANE",
    ),
    ResearchStageV1(
        "sol_organic_followup_v0",
        "organic_demand",
        "research",
        "Use a longer causal post-launch window to study independent net buyers and persistent demand instead of forcing all evidence into 5 seconds.",
        "fresh_causal_followup_capture",
        "PLANNED_SEPARATE_DETECTOR",
    ),
    ResearchStageV1(
        "sol_freeze_then_fresh_route_shadow",
        "opportunity_alpha",
        "research",
        "Freeze one mechanically justified candidate before a fresh independent route-shadow capture.",
        "fresh_independent_capture",
        "BLOCKED_UNTIL_DISCOVERY_CANDIDATE_EXISTS",
    ),
)

ROBINHOOD_PLAN_V1 = (
    ResearchStageV1(
        "rh_sequencer_feed_signal_plane_v1",
        "copyability_execution",
        "signal",
        "Use the Nitro sequencer feed as the primary low-latency observation path; keep RPC for reconciliation/fallback.",
        "reuse_feat_robinhood_sequencer_shadow_v0",
        "PORT_AND_BENCHMARK_FIRST",
    ),
    ResearchStageV1(
        "rh_pons_launch_adapter_v1",
        "manipulation_risk",
        "signal",
        "Reuse factory/launch/curve decoding from the existing Robinhood launch-burst branch behind the sequencer-fed Signal Plane.",
        "reuse_research_robinhood_launch_burst_v0",
        "SELECTIVE_PORT_REQUIRED",
    ),
    ResearchStageV1(
        "rh_protocol_opening_copyability_v0",
        "copyability_execution",
        "research",
        "Treat live opening tax, quote/slippage, launch phase and protocol caps as chain-native execution evidence rather than alpha.",
        "causally_observed_pons_contract_state_and_dry_run_quotes",
        "HIGH_PRIORITY_DIAGNOSTIC",
    ),
    ResearchStageV1(
        "rh_coordination_organicity_discovery_v0",
        "manipulation_risk",
        "research",
        "Adapt entity/buyer coordination and deployer-history features to EVM/Pons rather than inheriting Solana wallet thresholds.",
        "sequencer_observed_logs_transactions_and_prior_deployer_history",
        "PLANNED",
    ),
    ResearchStageV1(
        "rh_wallet_intelligence_v0",
        "wallet_intelligence",
        "research",
        "Keep trader/deployer quality separate from token quality and execution readiness.",
        "prior_only_wallet_and_deployer_history",
        "PLANNED_RESEARCH_PLANE",
    ),
    ResearchStageV1(
        "rh_routeable_edge_shadow_v0",
        "opportunity_alpha",
        "research",
        "Evaluate alpha only on entries that pass chain-native opening-tax/quote/risk feasibility.",
        "fresh_no_capital_route_shadow",
        "BLOCKED_UNTIL_SIGNAL_AND_COPYABILITY_INSTRUMENTATION_PASS",
    ),
    ResearchStageV1(
        "rh_freeze_then_fresh_validation_v0",
        "opportunity_alpha",
        "research",
        "Freeze the candidate rule before a fresh prospective sample; do not inherit Solana thresholds or exits.",
        "fresh_independent_robinhood_capture",
        "BLOCKED_UNTIL_DISCOVERY_CANDIDATE_EXISTS",
    ),
)

REUSE_CONTRACT_V1 = {
    "shared_across_chains": (
        "raw_evidence_before_parse",
        "local_receive_clock_and_causal_cutoff",
        "signal_plane_research_plane_separation",
        "feature_registry_and_fail_closed_missingness",
        "route_shadow_before_real_capital",
        "systems_scientific_economic_verdict_separation",
        "entity_adjusted_coordination_research_method",
        "prior_only_wallet_intelligence_method",
        "freeze_then_fresh_validation",
    ),
    "must_not_be_inherited_across_chains": (
        "selector_thresholds",
        "five_second_window_as_universal_truth",
        "pump_reserve_or_curve_formulas",
        "provider_route_rules",
        "fees_slippage_and_exit_rules",
        "priority_fee_logic",
        "route_availability_semantics",
    ),
    "solana_sources": {
        "current_research_branch": "research/market-first-routeable-edge-discovery-v2",
        "current_research_head": "1cf51877ca4a8745a23af6f7fc99bb28c3f5c4d3",
    },
    "robinhood_sources": {
        "sequencer_branch": "feat/robinhood-sequencer-shadow-v0",
        "sequencer_head": "b99b6cb96a7c9c9db46b706816cdc3379f19ecdf",
        "launch_burst_branch": "research/robinhood-launch-burst-v0",
        "launch_burst_head": "295550e00e167d963d8ce1870f0fa4c502a99963",
    },
}

SCIENTIFIC_GUARDRAILS_V1 = (
    "NO_CROSS_CHAIN_THRESHOLD_INHERITANCE",
    "NO_PROVIDER_OR_POSTDECISION_EXECUTION_FIELD_AS_MARKET_SELECTOR_FEATURE",
    "NO_SAME_SAMPLE_THRESHOLD_SEARCH_TO_RESCUE_A_RESULT",
    "NO_ML_OR_AUTOTUNING_BEFORE_ADEQUATE_INDEPENDENT_ROUTE_USABLE_LABELS",
    "NO_SOCIAL_MARKET_CONVERGENCE_BEFORE_INDEPENDENT_TRACK_EVIDENCE",
    "NO_NEW_EXIT_OPTIMIZATION_UNTIL_ENTRY_ALPHA_HAS_A_PROSPECTIVE_CANDIDATE",
    "EXTERNAL_VENDOR_TAGS_START_IN_RESEARCH_PLANE_ONLY",
    "ROBINHOOD_OPENING_TAX_AND_PROTOCOL_CAPS_ARE_COPYABILITY_NOT_ALPHA",
    "SYSTEMS_PASS_DOES_NOT_IMPLY_SCIENTIFIC_OR_ECONOMIC_PASS",
)

HYPOTHESIS_OVERRIDES_V1 = {
    "H_ORGANIC_VS_COORDINATED_V0": {
        "status": "ENTITY_ADJUSTED_CAUSAL_DISCOVERY_REQUIRED_NOT_SELECTOR_READY",
        "reason": "Wallet addresses are not assumed to be independent economic entities.",
        "next_experiment": "sol_coordination_organicity_discovery_v0",
        "candidate_features": (
            "unique_buy_entity_count",
            "top_entity_gross_flow_share",
            "coordination_compression_ratio",
            "early_buyer_retention_ratio",
            "sell_pressure",
            "wash_or_churn_proxy",
        ),
        "threshold": None,
    },
    "H_LIQUIDITY_EXITABILITY_V0": {
        "status": "SIMPLE_RESERVE_AND_CURVE_GEOMETRY_NOT_PROMOTED",
        "reason": "Existing reserve/geometry diagnostics did not show strong routeability discrimination.",
        "next_experiment": "separate_provider_readiness_from_alpha_then_only_revisit_liquidity_if_mechanistically_new_evidence_exists",
        "threshold": None,
    },
}


def validate_alignment_v1() -> None:
    if len(set(DECISION_DIMENSIONS_V1)) != len(DECISION_DIMENSIONS_V1):
        raise ValueError("duplicate decision dimensions")
    if TRACKS_V1["convergence"] != "BLOCKED_UNTIL_INDEPENDENT_EVIDENCE_SUPPORTS_IT":
        raise ValueError("convergence must remain blocked")
    for plan_name, plan in (("solana", SOLANA_PLAN_V1), ("robinhood", ROBINHOOD_PLAN_V1)):
        ids = [stage.stage_id for stage in plan]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate {plan_name} stage ids")
        for stage in plan:
            if stage.dimension not in DECISION_DIMENSIONS_V1:
                raise ValueError(f"unknown dimension in {stage.stage_id}")
            if stage.plane not in {"signal", "research"}:
                raise ValueError(f"unknown plane in {stage.stage_id}")
    if SOLANA_PLAN_V1[0].stage_id != "sol_routeable_edge_discovery_v2":
        raise ValueError("Solana must finish routeable-only alpha discovery before new selector work")
    if ROBINHOOD_PLAN_V1[0].stage_id != "rh_sequencer_feed_signal_plane_v1":
        raise ValueError("Robinhood must establish sequencer-fed Signal Plane first")
    if "selector_thresholds" not in REUSE_CONTRACT_V1["must_not_be_inherited_across_chains"]:
        raise ValueError("cross-chain thresholds must remain isolated")
    if HYPOTHESIS_OVERRIDES_V1["H_ORGANIC_VS_COORDINATED_V0"]["threshold"] is not None:
        raise ValueError("coordination discovery must not define a threshold on the current sample")


def alignment_report_v1() -> dict[str, object]:
    validate_alignment_v1()
    return {
        "version": VERSION,
        "decision_dimensions": list(DECISION_DIMENSIONS_V1),
        "tracks": dict(TRACKS_V1),
        "solana_plan": [asdict(stage) for stage in SOLANA_PLAN_V1],
        "robinhood_plan": [asdict(stage) for stage in ROBINHOOD_PLAN_V1],
        "reuse_contract": REUSE_CONTRACT_V1,
        "external_research_placement": EXTERNAL_RESEARCH_PLACEMENT_V1,
        "scientific_guardrails": list(SCIENTIFIC_GUARDRAILS_V1),
        "hypothesis_overrides": HYPOTHESIS_OVERRIDES_V1,
    }


validate_alignment_v1()
