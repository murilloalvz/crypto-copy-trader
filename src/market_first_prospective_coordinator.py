"""Minimal Market-First prospective preparation coordinator.

This module owns no detector, provider, score, or economic hypothesis. It only freezes
one already-admitted market episode at a local causal T0, persists the exact T0 research
snapshot, and then schedules future outcome targets. The order is intentional: no
forward outcome schedule may be created from a reconstructed or mutable T0 payload.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.market_episode_research_snapshot import (
    MarketEpisodeResearchSnapshotV0,
    MarketRegimeResearchFactsV0,
    build_market_episode_research_snapshot_v0,
)
from src.market_episode_research_snapshot_store import (
    MarketEpisodeResearchSnapshotRecordV0,
    persist_market_episode_research_snapshot_v0,
)
from src.market_intelligence_baseline import MarketIntelligenceBaselineV0
from src.market_opportunity_episode_store import (
    MarketOpportunityEpisode,
    freeze_market_opportunity_decision_as_of,
    get_market_opportunity_episode,
)
from src.opportunity_forward_outcome_store import (
    FORWARD_OUTCOME_HORIZONS_SECONDS,
    OpportunityForwardOutcome,
    schedule_opportunity_forward_outcomes,
)
from src.pump_creation_mode_facts import PumpCreationModeFactsV0


MARKET_FIRST_PROSPECTIVE_COORDINATOR_VERSION = "market_first_prospective_coordinator_v0"


@dataclass(frozen=True)
class MarketFirstProspectivePreparationV0:
    method_version: str
    episode: MarketOpportunityEpisode
    snapshot: MarketEpisodeResearchSnapshotV0
    snapshot_record: MarketEpisodeResearchSnapshotRecordV0
    forward_outcomes: tuple[OpportunityForwardOutcome, ...]


def prepare_market_first_prospective_episode_v0(
    *,
    episode_key: str,
    decision_as_of: int,
    market_intelligence: MarketIntelligenceBaselineV0,
    pump_creation_mode: PumpCreationModeFactsV0,
    regime: MarketRegimeResearchFactsV0 | None = None,
    horizons_seconds: tuple[int, ...] = FORWARD_OUTCOME_HORIZONS_SECONDS,
) -> MarketFirstProspectivePreparationV0:
    """Freeze and persist exact T0 before scheduling future outcome targets.

    Preconditions are checked against the persisted episode before `decision_as_of` is
    mutated, so malformed/cross-token/mismatched-local-clock inputs cannot accidentally
    freeze an episode. Once frozen, replay is idempotent only when the same exact T0
    snapshot is reproduced; a divergent replay fails closed in the snapshot store.

    No price/quote provider is called here. Scheduling creates PENDING future targets only.
    """

    key = str(episode_key).strip()
    if not key:
        raise ValueError("episode_key cannot be empty")
    decision = int(decision_as_of)
    if decision < 0:
        raise ValueError("decision_as_of must be non-negative")

    episode = get_market_opportunity_episode(key)
    if episode is None:
        raise ValueError(f"market opportunity episode not found: {key}")
    if episode.decision_as_of is not None and int(episode.decision_as_of) != decision:
        raise ValueError("market episode decision_as_of is already frozen with a different value")
    if decision < episode.first_trigger_observed_at:
        raise ValueError("decision_as_of cannot precede first trigger observation")
    if market_intelligence.token_mint != episode.token_mint:
        raise ValueError("market intelligence token_mint must match episode")
    if pump_creation_mode.token_mint != episode.token_mint:
        raise ValueError("pump creation mode token_mint must match episode")
    if market_intelligence.as_of != decision:
        raise ValueError("market intelligence as_of must equal requested decision_as_of")
    if pump_creation_mode.as_of != decision:
        raise ValueError("pump creation mode as_of must equal requested decision_as_of")

    frozen = freeze_market_opportunity_decision_as_of(key, decision_as_of=decision)
    snapshot = build_market_episode_research_snapshot_v0(
        episode=frozen,
        market_intelligence=market_intelligence,
        pump_creation_mode=pump_creation_mode,
        regime=regime,
    )
    snapshot_record = persist_market_episode_research_snapshot_v0(snapshot)
    outcomes = schedule_opportunity_forward_outcomes(
        frozen,
        horizons_seconds=horizons_seconds,
    )
    return MarketFirstProspectivePreparationV0(
        method_version=MARKET_FIRST_PROSPECTIVE_COORDINATOR_VERSION,
        episode=frozen,
        snapshot=snapshot,
        snapshot_record=snapshot_record,
        forward_outcomes=outcomes,
    )
