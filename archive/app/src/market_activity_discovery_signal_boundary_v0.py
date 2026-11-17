"""Durable first-trigger boundary for Market Activity Discovery V0.

This boundary belongs to the Signal Plane. It freezes the canonical first-trigger local
clock and creates exact +5m/+15m/+60m PENDING targets before any Research Plane work.
It performs no provider call, feature reconstruction, snapshot build, or economic analysis.

The operation is deliberately replay-safe rather than pretending to be cross-table atomic:
`freeze_market_opportunity_decision_as_of` is immutable/idempotent for the same T0 and
`schedule_opportunity_forward_outcomes` is idempotent for the same exact target clocks.
If a process dies between the two durable writes, replaying this boundary repairs the
missing schedule without moving T0. A divergent replay fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.market_opportunity_episode_store import (
    MarketOpportunityEpisode,
    freeze_market_opportunity_decision_as_of,
)
from src.opportunity_forward_outcome_store import (
    FORWARD_OUTCOME_HORIZONS_SECONDS,
    OpportunityForwardOutcome,
    schedule_opportunity_forward_outcomes,
)


MARKET_ACTIVITY_DISCOVERY_SIGNAL_BOUNDARY_VERSION = (
    "market_activity_discovery_signal_boundary_v0_first_trigger_schedule"
)


@dataclass(frozen=True)
class MarketActivityDiscoverySignalBoundaryV0:
    method_version: str
    episode: MarketOpportunityEpisode
    forward_outcomes: tuple[OpportunityForwardOutcome, ...]


def seal_market_activity_discovery_signal_boundary_v0(
    episode: MarketOpportunityEpisode,
    *,
    horizons_seconds: tuple[int, ...] = FORWARD_OUTCOME_HORIZONS_SECONDS,
) -> MarketActivityDiscoverySignalBoundaryV0:
    """Freeze canonical T0 and durably create exact future targets before research work."""

    if not episode.episode_key.strip() or not episode.acquisition_run_key.strip():
        raise ValueError("episode identity is incomplete")
    if not episode.first_trigger_key.strip() or not episode.token_mint.strip():
        raise ValueError("episode first-trigger identity is incomplete")

    decision = int(episode.first_trigger_observed_at)
    if decision < 0 or int(episode.first_trigger_chain_time) < 0:
        raise ValueError("episode first-trigger clocks must be non-negative")
    if episode.decision_as_of is not None and int(episode.decision_as_of) != decision:
        raise ValueError("episode decision_as_of conflicts with canonical first-trigger T0")

    horizons = tuple(int(item) for item in horizons_seconds)
    if not horizons or any(item <= 0 for item in horizons) or len(set(horizons)) != len(horizons):
        raise ValueError("forward horizons must be unique positive seconds")

    frozen = freeze_market_opportunity_decision_as_of(
        episode.episode_key,
        decision_as_of=decision,
    )
    if frozen.decision_as_of != decision:
        raise RuntimeError("signal boundary failed to freeze canonical first-trigger T0")

    outcomes = schedule_opportunity_forward_outcomes(
        frozen,
        horizons_seconds=horizons,
    )
    expected = [(horizon, decision + horizon) for horizon in horizons]
    actual = [(item.horizon_seconds, item.target_at) for item in outcomes]
    if actual != expected:
        raise RuntimeError("signal boundary produced non-canonical forward target clocks")
    if any(item.decision_as_of != decision for item in outcomes):
        raise RuntimeError("signal boundary produced an outcome with divergent T0")

    return MarketActivityDiscoverySignalBoundaryV0(
        method_version=MARKET_ACTIVITY_DISCOVERY_SIGNAL_BOUNDARY_VERSION,
        episode=frozen,
        forward_outcomes=outcomes,
    )
