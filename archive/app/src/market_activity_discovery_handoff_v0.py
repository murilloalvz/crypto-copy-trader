"""Pure Signal-Plane -> Research-Plane handoff contract for Market Activity Discovery V0.

This module performs no persistence, provider call, feature computation, queue operation,
or outcome scheduling. It only turns the canonical first MarketOpportunityEpisode trigger
into a stable envelope that a bounded Research Plane handoff may enqueue. Continuation
triggers return ``None`` and therefore cannot create duplicate research admissions.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.market_opportunity_episode_store import MarketOpportunityEpisode


MARKET_ACTIVITY_DISCOVERY_HANDOFF_VERSION = (
    "market_activity_discovery_handoff_v0_first_trigger_only"
)


@dataclass(frozen=True)
class MarketActivityDiscoveryHandoffV0:
    method_version: str
    handoff_key: str
    acquisition_run_key: str
    episode_key: str
    token_mint: str
    first_trigger_key: str
    decision_as_of: int
    chain_as_of: int


def build_market_activity_discovery_handoff_v0(
    *,
    episode: MarketOpportunityEpisode,
    trigger_key: str,
) -> MarketActivityDiscoveryHandoffV0 | None:
    """Return a stable envelope only for the canonical first trigger of an episode."""

    current_trigger = str(trigger_key).strip()
    if not current_trigger:
        raise ValueError("trigger_key cannot be empty")
    if not episode.acquisition_run_key.strip() or not episode.episode_key.strip():
        raise ValueError("episode run/key identity cannot be empty")
    if not episode.token_mint.strip() or not episode.first_trigger_key.strip():
        raise ValueError("episode token/first-trigger identity cannot be empty")
    if int(episode.first_trigger_observed_at) < 0 or int(episode.first_trigger_chain_time) < 0:
        raise ValueError("episode first-trigger clocks must be non-negative")

    if current_trigger != episode.first_trigger_key:
        return None

    handoff_key = (
        f"market-activity-handoff:v0:{episode.acquisition_run_key}:"
        f"{episode.episode_key}:{episode.first_trigger_key}"
    )
    return MarketActivityDiscoveryHandoffV0(
        method_version=MARKET_ACTIVITY_DISCOVERY_HANDOFF_VERSION,
        handoff_key=handoff_key,
        acquisition_run_key=episode.acquisition_run_key,
        episode_key=episode.episode_key,
        token_mint=episode.token_mint,
        first_trigger_key=episode.first_trigger_key,
        decision_as_of=int(episode.first_trigger_observed_at),
        chain_as_of=int(episode.first_trigger_chain_time),
    )
