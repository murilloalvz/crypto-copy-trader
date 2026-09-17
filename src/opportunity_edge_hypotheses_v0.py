from __future__ import annotations

from dataclasses import asdict, dataclass

from src.opportunity_feature_matrix_v0 import (
    TRACK_MARKET_FIRST,
    assert_selector_features_eligible_v0,
    feature_spec_v0,
)


VERSION = "opportunity_edge_hypotheses_v0"


@dataclass(frozen=True)
class EdgeHypothesisV0:
    hypothesis_id: str
    track: str
    family: str
    question: str
    selector_feature_ids: tuple[str, ...]
    diagnostic_feature_ids: tuple[str, ...]
    scientific_status: str
    selector_ready: bool
    threshold_contract: str
    preregistration_rule: str
    next_experiment_role: str
    blocker: str | None = None


_HYPOTHESES = (
    EdgeHypothesisV0(
        hypothesis_id="H_FLOW_QUALITY_V0",
        track=TRACK_MARKET_FIRST,
        family="flow_quality",
        question="Is early flow genuinely directional rather than mostly churn?",
        selector_feature_ids=(
            "signed_flow_over_event_reserve",
            "directional_flow_efficiency",
        ),
        diagnostic_feature_ids=(),
        scientific_status="EXISTING_SNIPER_V1_PREREGISTERED_COMPONENTS",
        selector_ready=True,
        threshold_contract="FROZEN_SNIPER_V1_ONLY_NO_RETUNING",
        preregistration_rule="Any new threshold or derived flow feature requires a new preregistration before fresh outcomes.",
        next_experiment_role="replicate_existing_frozen_selector_component",
    ),
    EdgeHypothesisV0(
        hypothesis_id="H_PARTICIPATION_BREADTH_V0",
        track=TRACK_MARKET_FIRST,
        family="participation_breadth",
        question="Does the move contain multiple independent buyers and transactions early enough to be copied?",
        selector_feature_ids=(
            "unique_buy_wallet_count",
            "unique_transaction_count",
        ),
        diagnostic_feature_ids=(),
        scientific_status="EXISTING_SNIPER_V1_PREREGISTERED_COMPONENTS",
        selector_ready=True,
        threshold_contract="FROZEN_SNIPER_V1_ONLY_NO_RETUNING",
        preregistration_rule="Do not derive higher/lower breadth thresholds from screening outcomes.",
        next_experiment_role="replicate_existing_frozen_selector_component",
    ),
    EdgeHypothesisV0(
        hypothesis_id="H_CONCENTRATION_V0",
        track=TRACK_MARKET_FIRST,
        family="concentration",
        question="Is early gross flow distributed enough that one wallet cannot explain most of the move?",
        selector_feature_ids=("top_wallet_gross_flow_share_worst_case_pct",),
        diagnostic_feature_ids=(),
        scientific_status="EXISTING_SNIPER_V1_PREREGISTERED_COMPONENT",
        selector_ready=True,
        threshold_contract="FROZEN_SNIPER_V1_ONLY_NO_RETUNING",
        preregistration_rule="Keep worst-case unidentified-flow semantics and do not retune concentration from observed outcomes.",
        next_experiment_role="replicate_existing_frozen_selector_component",
    ),
    EdgeHypothesisV0(
        hypothesis_id="H_ORGANIC_VS_COORDINATED_V0",
        track=TRACK_MARKET_FIRST,
        family="organic_vs_coordinated_flow",
        question="Does entity-adjusted breadth, concentration, funding context and post-decision behavior distinguish organic from coordinated activity better than raw wallet counts?",
        selector_feature_ids=(
            "unique_buy_wallet_count",
            "unique_transaction_count",
            "top_wallet_gross_flow_share_worst_case_pct",
        ),
        diagnostic_feature_ids=(
            "mf_unique_buy_entity_count",
            "mf_top_entity_gross_flow_share_pct",
            "mf_coordination_compression_ratio",
            "mf_entity_repeat_event_share_pct",
            "mf_entity_churn_proxy",
            "mf_funding_linked_buy_wallet_share_pct",
            "mf_deployer_prior_launch_count",
            "mf_early_buyer_retention_ratio_followup",
            "mf_sell_pressure_followup_ratio",
        ),
        scientific_status="ENTITY_ADJUSTED_CAUSAL_DIAGNOSTICS_REGISTERED_NOT_SELECTOR_READY",
        selector_ready=False,
        threshold_contract="NO_NEW_COMPOSITE_THRESHOLD_DEFINED",
        preregistration_rule=(
            "Entity/funding/deployer evidence used at decision time must have causal observation clocks no later than the decision cutoff. "
            "Followup retention and sell pressure are future-dependent diagnostics only. Any selector rule or threshold must be frozen before a fresh capture; Sniper V1 remains unchanged."
        ),
        next_experiment_role="entity_coordination_diagnostic_discovery_only",
        blocker="causal_entity_evidence_source_and_prospective_selector_rule_not_preregistered",
    ),
    EdgeHypothesisV0(
        hypothesis_id="H_ACCELERATION_V0",
        track=TRACK_MARKET_FIRST,
        family="acceleration",
        question="Is unique-buyer or buy-flow demand accelerating inside the causal evidence window?",
        selector_feature_ids=(),
        diagnostic_feature_ids=(
            "mf_event_rate_acceleration_per_s2",
            "mf_buy_event_rate_acceleration_per_s2",
            "mf_unique_buy_wallet_arrival_acceleration_per_s2",
            "mf_signed_flow_acceleration_per_s2",
            "mf_directional_efficiency_delta_late_minus_early",
            "mf_top_wallet_gross_share_delta_pct_points_late_minus_early",
        ),
        scientific_status="CAUSAL_DIAGNOSTIC_FEATURES_REGISTERED_NOT_SELECTOR_READY",
        selector_ready=False,
        threshold_contract="NO_THRESHOLD_DEFINED_DO_NOT_SWEEP",
        preregistration_rule=(
            "Use preserved causal 5s event sequences for diagnostic discovery only. Any selector rule or threshold "
            "must be separately frozen before a fresh prospective capture."
        ),
        next_experiment_role="retrospective_discovery_then_preregister_fresh_hypothesis",
        blocker="prospective_selector_rule_not_preregistered",
    ),
    EdgeHypothesisV0(
        hypothesis_id="H_LIQUIDITY_EXITABILITY_V0",
        track=TRACK_MARKET_FIRST,
        family="liquidity_exitability",
        question="Is there market-observable liquidity early enough to inform selection without leaking provider execution results?",
        selector_feature_ids=(),
        diagnostic_feature_ids=(
            "mf_pump_real_quote_reserve_raw_at_cutoff",
            "mf_pump_real_to_virtual_quote_reserve_ratio_at_cutoff",
            "mf_pump_real_quote_reserve_change_over_virtual_start",
            "provider_price_impact_pct_points",
        ),
        scientific_status="CAUSAL_MARKET_RESERVE_DIAGNOSTICS_REGISTERED_NOT_SELECTOR_READY",
        selector_ready=False,
        threshold_contract="NO_CAUSAL_MARKET_LIQUIDITY_THRESHOLD_DEFINED",
        preregistration_rule=(
            "Use event-native Pump reserve state only as causal diagnostic features and provider route results only as "
            "post-decision evaluation labels. Any selector rule or threshold requires separate preregistration before a fresh capture."
        ),
        next_experiment_role="retrospective_route_feasibility_association_only",
        blocker="prospective_liquidity_selector_rule_not_preregistered",
    ),
)

EDGE_HYPOTHESES_V0 = {item.hypothesis_id: item for item in _HYPOTHESES}


def validate_edge_hypotheses_v0() -> None:
    if len(EDGE_HYPOTHESES_V0) != len(_HYPOTHESES):
        raise ValueError("edge hypothesis matrix contains duplicate hypothesis_id values")
    for item in _HYPOTHESES:
        if item.track != TRACK_MARKET_FIRST:
            raise ValueError(f"v0 edge hypothesis must remain Market-First: {item.hypothesis_id}")
        for feature_id in item.selector_feature_ids:
            feature_spec_v0(feature_id)
        for feature_id in item.diagnostic_feature_ids:
            feature_spec_v0(feature_id)
        if item.selector_ready:
            if not item.selector_feature_ids:
                raise ValueError(f"selector-ready hypothesis has no selector features: {item.hypothesis_id}")
            assert_selector_features_eligible_v0(
                item.selector_feature_ids,
                selector_track=TRACK_MARKET_FIRST,
            )
        if item.threshold_contract == "NO_THRESHOLD_DEFINED_DO_NOT_SWEEP" and item.selector_ready:
            raise ValueError(f"unthresholded hypothesis cannot be selector-ready: {item.hypothesis_id}")


def edge_hypothesis_rows_v0() -> list[dict[str, object]]:
    validate_edge_hypotheses_v0()
    rows: list[dict[str, object]] = []
    for item in _HYPOTHESES:
        row = asdict(item)
        row["selector_feature_ids"] = list(item.selector_feature_ids)
        row["diagnostic_feature_ids"] = list(item.diagnostic_feature_ids)
        rows.append(row)
    return rows


validate_edge_hypotheses_v0()
