from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from src.participant_distribution_research import ParticipantDistributionWindow
from src.temporal_flow_structure_research import TemporalFlowStructureWindow


OPPORTUNITY_MULTIVARIATE_RESEARCH_VERSION = (
    "opportunity_multivariate_research_v1_outcome_blind_component_vector"
)


@dataclass(frozen=True)
class InteractionFamilySpec:
    key: str
    left_family: str
    right_family: str
    research_question: str


INTERACTION_FAMILY_SPECS = (
    InteractionFamilySpec(
        key="intensity_x_participant_distribution",
        left_family="intensity",
        right_family="participant_distribution",
        research_question=(
            "Does activity level mean something different when the same events are broadly "
            "distributed versus concentrated among a few observed addresses?"
        ),
    ),
    InteractionFamilySpec(
        key="direction_x_participant_distribution",
        left_family="direction",
        right_family="participant_distribution",
        research_question=(
            "Does buy/sell composition carry different information when BUY activity is broad "
            "versus dominated by a small set of observed addresses?"
        ),
    ),
    InteractionFamilySpec(
        key="intensity_x_temporal_structure",
        left_family="intensity",
        right_family="temporal_structure",
        research_question=(
            "Does high activity differ when it is sustained across market-time subwindows rather "
            "than concentrated in a short burst?"
        ),
    ),
    InteractionFamilySpec(
        key="participant_distribution_x_temporal_structure",
        left_family="participant_distribution",
        right_family="temporal_structure",
        research_question=(
            "Does broad or concentrated participation differ when the activity persists through "
            "time versus appearing in one burst?"
        ),
    ),
    InteractionFamilySpec(
        key="direction_x_temporal_structure",
        left_family="direction",
        right_family="temporal_structure",
        research_question=(
            "Does buy/sell composition differ when directional activity is persistent versus "
            "temporally concentrated?"
        ),
    ),
)


_SCIENCE_CAUTIONS = (
    "component_vector_is_not_an_entry_score",
    "interaction_family_is_not_economic_evidence",
    "failed_univariate_rule_may_reenter_only_as_a_new_interaction_hypothesis",
    "interaction_discovery_requires_fresh_data_and_separate_prospective_validation",
    "no_outcome_labels_are_accepted_by_this_builder",
)


@dataclass(frozen=True)
class OutcomeBlindOpportunityVector:
    """Causal, outcome-blind components that may later support interaction research.

    This object intentionally cannot carry forward returns, PnL labels, favorable bins, weights,
    or an entry score. It is a representation layer, not a strategy.
    """

    method_version: str
    episode_key: str
    token_mint: str
    episode_t0: int
    research_decision_as_of: int
    features: tuple[tuple[str, float | int | None], ...]
    feature_observed_at: tuple[tuple[str, int], ...]
    interaction_families: tuple[str, ...]
    data_quality_flags: tuple[str, ...]
    science_cautions: tuple[str, ...]

    def feature_dict(self) -> dict[str, float | int | None]:
        return dict(self.features)

    def clock_dict(self) -> dict[str, int]:
        return dict(self.feature_observed_at)


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _validate_base_features(
    *,
    base_features: Mapping[str, float | int | None],
    base_feature_observed_at: Mapping[str, int],
    decision_as_of: int,
) -> None:
    if set(base_features) != set(base_feature_observed_at):
        raise ValueError("base feature values and clocks must have identical keys")
    for name, observed_at in base_feature_observed_at.items():
        _required(name, "base feature name")
        if int(observed_at) < 0:
            raise ValueError("base feature observed_at must be non-negative")
        if int(observed_at) > decision_as_of:
            raise ValueError(f"base feature {name} observed after research decision")


def build_outcome_blind_opportunity_vector(
    *,
    episode_key: str,
    token_mint: str,
    episode_t0: int,
    research_decision_as_of: int,
    base_features: Mapping[str, float | int | None],
    base_feature_observed_at: Mapping[str, int],
    participant: ParticipantDistributionWindow,
    temporal: TemporalFlowStructureWindow,
) -> OutcomeBlindOpportunityVector:
    """Join complementary causal measurements without constructing an economic score.

    The component market windows must be anchored to the same episode T0. Their knowledge cutoffs
    may be earlier than or equal to the research decision, never later. The builder accepts no
    outcome argument by design, preventing label-driven feature construction at this layer.
    """

    key = _required(episode_key, "episode_key")
    token = _required(token_mint, "token_mint")
    t0 = int(episode_t0)
    decision = int(research_decision_as_of)
    if t0 < 0 or decision < 0:
        raise ValueError("episode and decision timestamps must be non-negative")
    if t0 > decision:
        raise ValueError("episode_t0 cannot be after research_decision_as_of")

    _validate_base_features(
        base_features=base_features,
        base_feature_observed_at=base_feature_observed_at,
        decision_as_of=decision,
    )

    if participant.token_mint != token or temporal.token_mint != token:
        raise ValueError("component token_mint does not match opportunity token")
    if participant.market_anchor_time != t0:
        raise ValueError("participant market anchor must equal episode_t0")
    if temporal.market_anchor_time != t0:
        raise ValueError("temporal market anchor must equal episode_t0")
    if participant.as_of > decision:
        raise ValueError("participant evidence observed after research decision")
    if temporal.knowledge_as_of > decision:
        raise ValueError("temporal evidence observed after research decision")

    merged: dict[str, float | int | None] = dict(base_features)
    clocks: dict[str, int] = {name: int(value) for name, value in base_feature_observed_at.items()}

    participant_prefix = f"participant{participant.window_seconds}"
    participant_values: dict[str, float | int | None] = {
        f"{participant_prefix}_buy_event_count": participant.buy_event_count,
        f"{participant_prefix}_known_unique_buy_wallet_count": (
            participant.known_unique_buy_wallet_count
        ),
        f"{participant_prefix}_buyer_wallet_identity_coverage_pct": (
            participant.buyer_wallet_identity_coverage_pct
        ),
        f"{participant_prefix}_buyer_breadth_ratio": participant.buyer_breadth_ratio,
        f"{participant_prefix}_buyer_repeated_event_share_pct": (
            participant.buyer_repeated_event_share_pct
        ),
        f"{participant_prefix}_top1_buyer_event_share_pct": (
            participant.top1_buyer_event_share_pct
        ),
        f"{participant_prefix}_top3_buyer_event_share_pct": (
            participant.top3_buyer_event_share_pct
        ),
        f"{participant_prefix}_buy_event_hhi": participant.participant_buy_event_hhi,
    }

    temporal_prefix = f"temporal{temporal.lookback_seconds}"
    temporal_values: dict[str, float | int | None] = {
        f"{temporal_prefix}_event_count": temporal.market_event_count,
        f"{temporal_prefix}_active_subwindow_count": temporal.active_subwindow_count,
        f"{temporal_prefix}_active_subwindow_share_pct": temporal.active_subwindow_share_pct,
        f"{temporal_prefix}_max_subwindow_event_share_pct": (
            temporal.max_subwindow_event_share_pct
        ),
        f"{temporal_prefix}_event_hhi": temporal.temporal_event_hhi,
        f"{temporal_prefix}_late_event_share_pct": temporal.late_event_share_pct,
        f"{temporal_prefix}_late_to_early_event_ratio": temporal.late_to_early_event_ratio,
        f"{temporal_prefix}_buy_active_subwindow_count": temporal.buy_active_subwindow_count,
    }

    for values, observed_at in (
        (participant_values, participant.as_of),
        (temporal_values, temporal.knowledge_as_of),
    ):
        collisions = set(values).intersection(merged)
        if collisions:
            raise ValueError(f"component feature name collision: {sorted(collisions)}")
        merged.update(values)
        clocks.update({name: int(observed_at) for name in values})

    quality = tuple(
        [f"participant:{flag}" for flag in participant.data_quality_flags]
        + [f"temporal:{flag}" for flag in temporal.data_quality_flags]
    )

    return OutcomeBlindOpportunityVector(
        method_version=OPPORTUNITY_MULTIVARIATE_RESEARCH_VERSION,
        episode_key=key,
        token_mint=token,
        episode_t0=t0,
        research_decision_as_of=decision,
        features=tuple(sorted(merged.items())),
        feature_observed_at=tuple(sorted(clocks.items())),
        interaction_families=tuple(spec.key for spec in INTERACTION_FAMILY_SPECS),
        data_quality_flags=quality,
        science_cautions=_SCIENCE_CAUTIONS,
    )
