"""Minimal admission coordinator for the preregistered Market Activity discovery V0.

This module does not detect opportunities or query providers. It only enforces the frozen
six-hour run boundary before either registering a denominator-only episode or delegating
to the existing Market-First prospective T0 coordinator and then registering exact T0
lineage in the immutable discovery cohort.

For this discovery protocol both scientific admission time and causal local T0 are frozen
exactly at the canonical MarketOpportunityEpisode ``first_trigger_observed_at``. The
independent on-chain anchor remains ``first_trigger_chain_time``. Research-worker queue
latency therefore cannot move an episode into or out of the six-hour denominator window.
Later enrichment/quotes must not move T0 forward or be backfilled into the snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.market_activity_discovery_cohort_v0 import (
    MarketActivityDiscoveryCohortMemberV0,
    register_market_activity_discovery_member_v0,
)
from src.market_activity_discovery_run_v0 import (
    MarketActivityDiscoveryRunV0,
    assert_market_activity_discovery_admission_open_v0,
    load_market_activity_discovery_run_v0,
)
from src.market_activity_dynamics_v0 import MarketActivityDynamicsV0
from src.market_episode_research_snapshot import MarketRegimeResearchFactsV0
from src.market_episode_research_snapshot_store import MarketEpisodeResearchSnapshotRecordV0
from src.market_first_prospective_coordinator import (
    MarketFirstProspectivePreparationV0,
    prepare_market_first_prospective_episode_v0,
)
from src.market_intelligence_baseline import MarketIntelligenceBaselineV0
from src.market_opportunity_episode_store import get_market_opportunity_episode
from src.opportunity_forward_outcome_store import FORWARD_OUTCOME_HORIZONS_SECONDS
from src.pump_creation_mode_facts import PumpCreationModeFactsV0


MARKET_ACTIVITY_DISCOVERY_ADMISSION_VERSION = (
    "market_activity_discovery_admission_v0_2_first_trigger_admission_and_t0"
)


@dataclass(frozen=True)
class MarketActivityDiscoveryAdmissionV0:
    method_version: str
    run: MarketActivityDiscoveryRunV0
    cohort_member: MarketActivityDiscoveryCohortMemberV0
    preparation: MarketFirstProspectivePreparationV0 | None


def _load_run_and_episode(*, acquisition_run_key: str, episode_key: str):
    run_key = str(acquisition_run_key).strip()
    key = str(episode_key).strip()
    if not run_key or not key:
        raise ValueError("acquisition_run_key and episode_key cannot be empty")
    run = load_market_activity_discovery_run_v0(acquisition_run_key=run_key)
    if run is None:
        raise ValueError("market activity discovery run not found")
    episode = get_market_opportunity_episode(key)
    if episode is None:
        raise ValueError("market opportunity episode not found")
    if episode.acquisition_run_key != run.acquisition_run_key:
        raise ValueError("episode acquisition_run_key must match discovery run")
    return run, episode


def _validate_first_trigger_admission_time(*, episode, considered_at: int) -> int:
    considered = int(considered_at)
    expected = int(episode.first_trigger_observed_at)
    if considered != expected:
        raise ValueError(
            "Market Activity discovery considered_at must equal first_trigger_observed_at"
        )
    return considered


def register_considered_market_activity_episode_v0(
    *,
    acquisition_run_key: str,
    episode_key: str,
    considered_at: int,
    snapshot_record: MarketEpisodeResearchSnapshotRecordV0 | None = None,
) -> MarketActivityDiscoveryAdmissionV0:
    """Register one first-trigger-considered episode without reconstructing T0.

    Scientific admission time is the canonical ``first_trigger_observed_at``, never the
    later Research Plane processing time. This path remains valid for missing/unfrozen T0;
    the first cohort disposition is immutable and cannot be upgraded after outcomes exist.
    """

    run, episode = _load_run_and_episode(
        acquisition_run_key=acquisition_run_key,
        episode_key=episode_key,
    )
    considered = _validate_first_trigger_admission_time(
        episode=episode,
        considered_at=considered_at,
    )
    assert_market_activity_discovery_admission_open_v0(run, considered_at=considered)
    member = register_market_activity_discovery_member_v0(
        cohort_key=run.cohort_key,
        episode=episode,
        considered_at=considered,
        snapshot_record=snapshot_record,
    )
    return MarketActivityDiscoveryAdmissionV0(
        method_version=MARKET_ACTIVITY_DISCOVERY_ADMISSION_VERSION,
        run=run,
        cohort_member=member,
        preparation=None,
    )


def prepare_and_register_market_activity_episode_v0(
    *,
    acquisition_run_key: str,
    episode_key: str,
    considered_at: int,
    decision_as_of: int,
    market_intelligence: MarketIntelligenceBaselineV0,
    pump_creation_mode: PumpCreationModeFactsV0,
    activity_dynamics: MarketActivityDynamicsV0,
    regime: MarketRegimeResearchFactsV0 | None = None,
    horizons_seconds: tuple[int, ...] = FORWARD_OUTCOME_HORIZONS_SECONDS,
) -> MarketActivityDiscoveryAdmissionV0:
    """Freeze/persist exact first-trigger T0, schedule outcomes, then register lineage.

    Both run admission and ``decision_as_of`` are anchored to the canonical episode's
    ``first_trigger_observed_at``. Research Plane processing delay is irrelevant to the
    denominator. Inputs must have been built with that local cutoff and with
    ``first_trigger_chain_time`` as their independent chain anchor.
    """

    run, episode = _load_run_and_episode(
        acquisition_run_key=acquisition_run_key,
        episode_key=episode_key,
    )
    considered = _validate_first_trigger_admission_time(
        episode=episode,
        considered_at=considered_at,
    )
    assert_market_activity_discovery_admission_open_v0(run, considered_at=considered)
    decision = int(decision_as_of)
    if decision != int(episode.first_trigger_observed_at):
        raise ValueError(
            "Market Activity discovery decision_as_of must equal first_trigger_observed_at"
        )
    if market_intelligence.chain_as_of != int(episode.first_trigger_chain_time):
        raise ValueError(
            "Market Activity discovery chain_as_of must equal first_trigger_chain_time"
        )
    if activity_dynamics.chain_as_of != int(episode.first_trigger_chain_time):
        raise ValueError(
            "Market Activity discovery Activity Dynamics chain_as_of must equal first_trigger_chain_time"
        )

    preparation = prepare_market_first_prospective_episode_v0(
        episode_key=episode_key,
        decision_as_of=decision,
        market_intelligence=market_intelligence,
        pump_creation_mode=pump_creation_mode,
        activity_dynamics=activity_dynamics,
        regime=regime,
        horizons_seconds=horizons_seconds,
    )
    member = register_market_activity_discovery_member_v0(
        cohort_key=run.cohort_key,
        episode=preparation.episode,
        considered_at=considered,
        snapshot_record=preparation.snapshot_record,
    )
    if not member.primary_analysis_eligible or member.disposition != "ANALYZABLE_T0":
        raise RuntimeError("successful T0 preparation did not register an analyzable cohort member")
    return MarketActivityDiscoveryAdmissionV0(
        method_version=MARKET_ACTIVITY_DISCOVERY_ADMISSION_VERSION,
        run=run,
        cohort_member=member,
        preparation=preparation,
    )
