"""Research-Plane adapter from IndexedMarketSignalKernel triggers to canonical episodes.

This replaces no Signal Plane component and must not run inside kernel computation. A
bounded Research Plane worker may receive the already-produced trigger plus the exact
source trade/event identity, persist the canonical MarketOpportunityEpisode using the
trigger's independent local/chain anchors, and emit a discovery handoff only if that
trigger became the episode's first canonical trigger.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.market_activity_discovery_handoff_v0 import (
    MarketActivityDiscoveryHandoffV0,
    build_market_activity_discovery_handoff_v0,
)
from src.market_opportunity_episode_store import (
    MarketOpportunityEpisode,
    assign_market_opportunity_trigger,
)
from src.market_opportunity_radar import MarketMovementTrigger, MarketTradeObservation


MARKET_ACTIVITY_DISCOVERY_EPISODE_ADAPTER_VERSION = (
    "market_activity_discovery_episode_adapter_v0_indexed_kernel"
)


@dataclass(frozen=True)
class MarketActivityDiscoveryEpisodeAdaptationV0:
    method_version: str
    trigger_key: str
    episode: MarketOpportunityEpisode
    discovery_handoff: MarketActivityDiscoveryHandoffV0 | None
    provider_calls_performed: int


def _stable_trigger_key(
    *,
    acquisition_run_key: str,
    source_event_key: str,
    trigger: MarketMovementTrigger,
) -> str:
    return (
        f"market-kernel-trigger:v0:{acquisition_run_key}:{source_event_key}:"
        f"{trigger.method_version}:{trigger.trigger_kind}"
    )


def persist_indexed_kernel_trigger_as_market_episode_v0(
    *,
    acquisition_run_key: str,
    source_event_key: str,
    source_trade: MarketTradeObservation,
    trigger: MarketMovementTrigger,
) -> MarketActivityDiscoveryEpisodeAdaptationV0:
    """Persist one already-computed kernel trigger and return first-trigger handoff if new."""

    run_key = str(acquisition_run_key).strip()
    event_key = str(source_event_key).strip()
    if not run_key or not event_key:
        raise ValueError("acquisition_run_key and source_event_key cannot be empty")
    if trigger.token_mint != source_trade.token_mint:
        raise ValueError("kernel trigger token_mint must match exact source trade")
    if trigger.features.token_mint != trigger.token_mint:
        raise ValueError("kernel trigger feature token_mint must match trigger")
    if int(trigger.as_of) != int(source_trade.observed_at):
        raise ValueError("kernel trigger local as_of must equal source trade observed_at")
    if trigger.features.as_of != trigger.as_of:
        raise ValueError("kernel trigger features as_of must match trigger")
    chain_anchor = trigger.features.chain_as_of
    if chain_anchor is None or int(chain_anchor) < 0:
        raise ValueError("kernel trigger requires a non-negative chain_as_of")
    if not trigger.method_version.strip() or not trigger.trigger_kind.strip() or not trigger.direction.strip():
        raise ValueError("kernel trigger method/kind/direction cannot be empty")

    trigger_key = _stable_trigger_key(
        acquisition_run_key=run_key,
        source_event_key=event_key,
        trigger=trigger,
    )
    episode = assign_market_opportunity_trigger(
        acquisition_run_key=run_key,
        trigger_key=trigger_key,
        token_mint=trigger.token_mint,
        trigger_kind=trigger.trigger_kind,
        direction=trigger.direction,
        chain_time=int(chain_anchor),
        observed_at=int(trigger.as_of),
        method_version=trigger.method_version,
        venue=source_trade.venue,
    )
    handoff = build_market_activity_discovery_handoff_v0(
        episode=episode,
        trigger_key=trigger_key,
    )
    return MarketActivityDiscoveryEpisodeAdaptationV0(
        method_version=MARKET_ACTIVITY_DISCOVERY_EPISODE_ADAPTER_VERSION,
        trigger_key=trigger_key,
        episode=episode,
        discovery_handoff=handoff,
        provider_calls_performed=0,
    )
