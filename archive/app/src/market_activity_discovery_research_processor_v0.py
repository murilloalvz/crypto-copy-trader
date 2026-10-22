"""Provider-free Research Plane processor for Market Activity Discovery V0 handoffs.

The Signal Plane is expected to enqueue only the pure first-trigger handoff envelope. This
processor validates that envelope against the persisted canonical episode, checks the
preregistered run boundary using the first-trigger local clock, builds same-run T0 from
persisted market trades, then delegates to the immutable admission/T0/outcome machinery.

It performs no network/provider call and is not intended to execute in the kernel or
stateful detector commit path.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.market_activity_discovery_admission_v0 import (
    MarketActivityDiscoveryAdmissionV0,
    prepare_and_register_market_activity_episode_v0,
)
from src.market_activity_discovery_handoff_v0 import MarketActivityDiscoveryHandoffV0
from src.market_activity_discovery_run_v0 import (
    assert_market_activity_discovery_admission_open_v0,
    load_market_activity_discovery_run_v0,
)
from src.market_activity_discovery_t0_builder_v0 import (
    MarketActivityDiscoveryT0BuildV0,
    build_market_activity_discovery_t0_v0,
)
from src.market_opportunity_episode_store import get_market_opportunity_episode


MARKET_ACTIVITY_DISCOVERY_RESEARCH_PROCESSOR_VERSION = (
    "market_activity_discovery_research_processor_v0_provider_free"
)


@dataclass(frozen=True)
class MarketActivityDiscoveryResearchProcessingV0:
    method_version: str
    handoff: MarketActivityDiscoveryHandoffV0
    t0_build: MarketActivityDiscoveryT0BuildV0
    admission: MarketActivityDiscoveryAdmissionV0
    provider_calls_performed: int


def _validate_handoff_against_episode(handoff, episode) -> None:
    expected = (
        episode.acquisition_run_key,
        episode.episode_key,
        episode.token_mint,
        episode.first_trigger_key,
        int(episode.first_trigger_observed_at),
        int(episode.first_trigger_chain_time),
    )
    actual = (
        handoff.acquisition_run_key,
        handoff.episode_key,
        handoff.token_mint,
        handoff.first_trigger_key,
        int(handoff.decision_as_of),
        int(handoff.chain_as_of),
    )
    if actual != expected:
        raise ValueError("Market Activity discovery handoff conflicts with canonical episode")


def process_market_activity_discovery_handoff_v0(
    handoff: MarketActivityDiscoveryHandoffV0,
) -> MarketActivityDiscoveryResearchProcessingV0:
    """Process one stable first-trigger envelope entirely in the Research Plane."""

    run = load_market_activity_discovery_run_v0(
        acquisition_run_key=handoff.acquisition_run_key,
    )
    if run is None:
        raise ValueError("market activity discovery run not found")
    episode = get_market_opportunity_episode(handoff.episode_key)
    if episode is None:
        raise ValueError("market opportunity episode not found")
    _validate_handoff_against_episode(handoff, episode)

    # Check the scientific run boundary before T0 work. This uses the canonical first
    # trigger clock, never worker processing time.
    assert_market_activity_discovery_admission_open_v0(
        run,
        considered_at=handoff.decision_as_of,
    )

    t0_build = build_market_activity_discovery_t0_v0(episode)
    if t0_build.provider_calls_performed != 0:
        raise RuntimeError("provider-free T0 builder unexpectedly performed provider work")

    admission = prepare_and_register_market_activity_episode_v0(
        acquisition_run_key=handoff.acquisition_run_key,
        episode_key=handoff.episode_key,
        considered_at=handoff.decision_as_of,
        decision_as_of=handoff.decision_as_of,
        market_intelligence=t0_build.market_intelligence,
        pump_creation_mode=t0_build.pump_creation_mode,
        activity_dynamics=t0_build.activity_dynamics,
    )
    return MarketActivityDiscoveryResearchProcessingV0(
        method_version=MARKET_ACTIVITY_DISCOVERY_RESEARCH_PROCESSOR_VERSION,
        handoff=handoff,
        t0_build=t0_build,
        admission=admission,
        provider_calls_performed=0,
    )
