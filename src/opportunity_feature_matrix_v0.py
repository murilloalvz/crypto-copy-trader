from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


VERSION = "opportunity_feature_matrix_v0"
TRACK_MARKET_FIRST = "market_first"
TRACK_SOCIAL_EVENT_FIRST = "social_event_first"
TRACK_CONVERGENCE_ONLY = "convergence_only"
VALID_TRACKS = {
    TRACK_MARKET_FIRST,
    TRACK_SOCIAL_EVENT_FIRST,
    TRACK_CONVERGENCE_ONLY,
}


@dataclass(frozen=True)
class OpportunityFeatureSpecV0:
    feature_id: str
    track: str
    category: str
    description: str
    causal_source: str
    earliest_causal_availability: str
    selector_eligible: bool
    diagnostic_only: bool
    execution_only: bool
    future_dependent: bool
    missing_data_policy: str
    normalization_scope: str
    chain_scope: tuple[str, ...]
    scientific_status: str
    hypothesis_role: str


_SNIPER_COMMON = {
    "track": TRACK_MARKET_FIRST,
    "causal_source": "frozen_market_feature_snapshot_before_provider_quotes",
    "earliest_causal_availability": "at_or_before_frozen_5s_decision_cutoff",
    "selector_eligible": True,
    "diagnostic_only": False,
    "execution_only": False,
    "future_dependent": False,
    "missing_data_policy": "fail_closed_insufficient_evidence",
    "normalization_scope": "pump_launch_frozen_5s_feature_snapshot",
    "chain_scope": ("solana:mainnet:pumpfun",),
    "scientific_status": "FROZEN_SNIPER_V1_PREREGISTERED_SELECTOR",
}

_DISCOVERY_COMMON = {
    "track": TRACK_MARKET_FIRST,
    "causal_source": "preserved_frozen_5s_trade_event_sequence_before_provider_quotes",
    "earliest_causal_availability": "at_frozen_5s_decision_cutoff",
    "selector_eligible": False,
    "diagnostic_only": True,
    "execution_only": False,
    "future_dependent": False,
    "missing_data_policy": "fail_closed_when_required_subwindow_or_identity_evidence_missing",
    "normalization_scope": "pump_launch_frozen_5s_subwindow_diagnostic_v1",
    "chain_scope": ("solana:mainnet:pumpfun",),
    "scientific_status": "DISCOVERY_DIAGNOSTIC_ONLY_NOT_PREREGISTERED_SELECTOR",
}


def _sniper(
    feature_id: str,
    *,
    category: str,
    description: str,
    hypothesis_role: str,
) -> OpportunityFeatureSpecV0:
    return OpportunityFeatureSpecV0(
        feature_id=feature_id,
        category=category,
        description=description,
        hypothesis_role=hypothesis_role,
        **_SNIPER_COMMON,
    )


def _discovery(
    feature_id: str,
    *,
    category: str,
    description: str,
    hypothesis_role: str,
) -> OpportunityFeatureSpecV0:
    return OpportunityFeatureSpecV0(
        feature_id=feature_id,
        category=category,
        description=description,
        hypothesis_role=hypothesis_role,
        **_DISCOVERY_COMMON,
    )


_FEATURES = (
    _sniper(
        "signed_flow_over_event_reserve",
        category="flow_quality",
        description="Signed frozen-window market flow normalized by event reserve.",
        hypothesis_role="flow_quality_directional_demand",
    ),
    _sniper(
        "event_count",
        category="participation_breadth",
        description="Trade-event count observed inside the frozen evidence window.",
        hypothesis_role="minimum_market_activity",
    ),
    _sniper(
        "directional_flow_efficiency",
        category="flow_quality",
        description="Signed normalized flow divided by gross normalized turnover.",
        hypothesis_role="directional_flow_vs_churn",
    ),
    _sniper(
        "wallet_identity_coverage_pct",
        category="evidence_coverage",
        description="Percent of frozen-window trade events carrying observed wallet identity.",
        hypothesis_role="wallet_evidence_sufficiency",
    ),
    _sniper(
        "wallet_gross_flow_coverage_pct",
        category="evidence_coverage",
        description="Percent of frozen-window gross flow attributable to identified wallets.",
        hypothesis_role="wallet_flow_evidence_sufficiency",
    ),
    _sniper(
        "unique_buy_wallet_count",
        category="participation_breadth",
        description="Unique BUY-wallet count inside the frozen evidence window.",
        hypothesis_role="independent_buyer_breadth",
    ),
    _sniper(
        "top_wallet_gross_flow_share_worst_case_pct",
        category="concentration",
        description="Conservative top-wallet concentration with all unidentified gross flow assigned to the largest identified wallet.",
        hypothesis_role="organic_vs_concentrated_flow",
    ),
    _sniper(
        "transaction_identity_coverage_pct",
        category="evidence_coverage",
        description="Percent of frozen-window trade events carrying observed transaction identity.",
        hypothesis_role="transaction_evidence_sufficiency",
    ),
    _sniper(
        "unique_transaction_count",
        category="participation_breadth",
        description="Unique observed transaction count inside the frozen evidence window.",
        hypothesis_role="independent_transaction_breadth",
    ),
    _discovery(
        "mf_event_rate_acceleration_per_s2",
        category="acceleration",
        description="Change in observed trade-event rate between the late and early 2.5s halves of the frozen 5s causal window, divided by half-center distance.",
        hypothesis_role="market_activity_acceleration_candidate",
    ),
    _discovery(
        "mf_buy_event_rate_acceleration_per_s2",
        category="acceleration",
        description="Change in BUY-event rate between the late and early 2.5s halves of the frozen 5s causal window, divided by half-center distance.",
        hypothesis_role="buy_demand_acceleration_candidate",
    ),
    _discovery(
        "mf_unique_buy_wallet_arrival_acceleration_per_s2",
        category="acceleration",
        description="Change in first-seen BUY-wallet arrival rate across the two causal half-windows; unavailable when wallet identity is incomplete.",
        hypothesis_role="independent_buyer_arrival_acceleration_candidate",
    ),
    _discovery(
        "mf_signed_flow_acceleration_per_s2",
        category="acceleration",
        description="Change in signed reserve-normalized flow rate across the two causal half-windows, divided by half-center distance.",
        hypothesis_role="directional_flow_acceleration_candidate",
    ),
    _discovery(
        "mf_directional_efficiency_delta_late_minus_early",
        category="flow_quality_dynamics",
        description="Late-half minus early-half signed-to-gross flow efficiency within the frozen causal window.",
        hypothesis_role="directional_quality_improvement_candidate",
    ),
    _discovery(
        "mf_top_wallet_gross_share_delta_pct_points_late_minus_early",
        category="concentration_dynamics",
        description="Late-half minus early-half top-wallet gross-flow share in percentage points; unavailable when wallet identity is incomplete.",
        hypothesis_role="concentration_dynamics_candidate",
    ),
    OpportunityFeatureSpecV0(
        feature_id="causal_capture_sha256",
        track=TRACK_MARKET_FIRST,
        category="research_provenance",
        description="Capture identity used to prevent copied/replayed artifacts from counting as independent replication.",
        causal_source="route_input_artifact_bytes",
        earliest_causal_availability="after_capture_artifact_materialization",
        selector_eligible=False,
        diagnostic_only=True,
        execution_only=False,
        future_dependent=False,
        missing_data_policy="required_for_replication_accounting_not_imputed",
        normalization_scope="research_plane_capture_provenance",
        chain_scope=("solana:mainnet:pumpfun",),
        scientific_status="DIAGNOSTIC_RESEARCH_PROVENANCE_ONLY",
        hypothesis_role="independent_replication_accounting",
    ),
    OpportunityFeatureSpecV0(
        feature_id="provider_price_impact_pct_points",
        track=TRACK_MARKET_FIRST,
        category="execution_feasibility",
        description="Provider route price-impact result obtained from execution-side quoting/assembly.",
        causal_source="post_decision_execution_provider",
        earliest_causal_availability="after_provider_request",
        selector_eligible=False,
        diagnostic_only=False,
        execution_only=True,
        future_dependent=False,
        missing_data_policy="unavailable_not_imputed",
        normalization_scope="route_shadow_execution_evidence",
        chain_scope=("solana:mainnet:pumpfun",),
        scientific_status="EXECUTION_ONLY_NOT_SELECTOR_EVIDENCE",
        hypothesis_role="execution_feasibility_only",
    ),
    OpportunityFeatureSpecV0(
        feature_id="future_return_60s",
        track=TRACK_MARKET_FIRST,
        category="outcome",
        description="Return measured sixty seconds after the decision/entry horizon.",
        causal_source="future_outcome_observation",
        earliest_causal_availability="after_60s_outcome_horizon",
        selector_eligible=False,
        diagnostic_only=False,
        execution_only=False,
        future_dependent=True,
        missing_data_policy="outcome_only_never_imputed_into_selector",
        normalization_scope="research_plane_outcomes",
        chain_scope=("solana:mainnet:pumpfun",),
        scientific_status="OUTCOME_ONLY_FORBIDDEN_IN_SELECTOR",
        hypothesis_role="economic_outcome_measurement",
    ),
    OpportunityFeatureSpecV0(
        feature_id="observed_event_count",
        track=TRACK_SOCIAL_EVENT_FIRST,
        category="social_attention",
        description="Count of Social/Event observations causally available by the declared cutoff.",
        causal_source="social_event_evidence_observed_and_mapped_clock",
        earliest_causal_availability="after_real_observation_and_token_mapping",
        selector_eligible=False,
        diagnostic_only=False,
        execution_only=False,
        future_dependent=False,
        missing_data_policy="insufficient_evidence_no_imputation",
        normalization_scope="social_event_snapshot_v0",
        chain_scope=("cross_chain_subject_mapping",),
        scientific_status="CAUSAL_FEATURE_NO_PREREGISTERED_SELECTOR_YET",
        hypothesis_role="social_attention_breadth_candidate",
    ),
)

FEATURE_MATRIX_V0 = {feature.feature_id: feature for feature in _FEATURES}


def validate_feature_matrix_v0() -> None:
    if len(FEATURE_MATRIX_V0) != len(_FEATURES):
        raise ValueError("feature matrix contains duplicate feature_id values")
    for feature in _FEATURES:
        if not feature.feature_id.strip():
            raise ValueError("feature_id must be non-empty")
        if feature.track not in VALID_TRACKS:
            raise ValueError(f"unsupported feature track: {feature.track}")
        if not feature.chain_scope:
            raise ValueError(f"feature {feature.feature_id} must declare chain_scope")
        if feature.selector_eligible and (
            feature.diagnostic_only or feature.execution_only or feature.future_dependent
        ):
            raise ValueError(
                f"feature {feature.feature_id} cannot be selector_eligible while diagnostic/execution/future-only"
            )


def feature_spec_v0(feature_id: str) -> OpportunityFeatureSpecV0:
    validate_feature_matrix_v0()
    key = str(feature_id).strip()
    feature = FEATURE_MATRIX_V0.get(key)
    if feature is None:
        raise ValueError(f"unregistered selector feature: {key or '<empty>'}")
    return feature


def feature_matrix_rows_v0() -> list[dict[str, object]]:
    validate_feature_matrix_v0()
    rows: list[dict[str, object]] = []
    for feature in _FEATURES:
        row = asdict(feature)
        row["chain_scope"] = list(feature.chain_scope)
        rows.append(row)
    return rows


def assert_selector_feature_eligible_v0(
    feature_id: str,
    *,
    selector_track: str,
    convergence_declared: bool = False,
) -> OpportunityFeatureSpecV0:
    if selector_track not in VALID_TRACKS:
        raise ValueError(f"unsupported selector track: {selector_track}")
    feature = feature_spec_v0(feature_id)

    if selector_track == TRACK_CONVERGENCE_ONLY:
        if not convergence_declared:
            raise ValueError("convergence selector requires explicit convergence declaration")
    elif feature.track != selector_track:
        raise ValueError(
            f"track leakage: feature {feature.feature_id} is {feature.track}, selector is {selector_track}; "
            "cross-track use requires an explicitly declared convergence selector"
        )

    if feature.future_dependent:
        raise ValueError(f"future-dependent feature forbidden in selector: {feature.feature_id}")
    if feature.execution_only:
        raise ValueError(f"execution-only feature forbidden in selector: {feature.feature_id}")
    if feature.diagnostic_only:
        raise ValueError(f"diagnostic-only feature forbidden in selector: {feature.feature_id}")
    if not feature.selector_eligible:
        raise ValueError(f"feature is not preregistered selector-eligible: {feature.feature_id}")
    return feature


def assert_selector_features_eligible_v0(
    feature_ids: Iterable[str],
    *,
    selector_track: str,
    convergence_declared: bool = False,
) -> tuple[OpportunityFeatureSpecV0, ...]:
    return tuple(
        assert_selector_feature_eligible_v0(
            feature_id,
            selector_track=selector_track,
            convergence_declared=convergence_declared,
        )
        for feature_id in feature_ids
    )


validate_feature_matrix_v0()
