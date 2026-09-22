from __future__ import annotations

from dataclasses import dataclass

from src.market_opportunity_episode_store import (
    MarketOpportunityEpisode,
    assign_market_opportunity_trigger,
)
from src.market_opportunity_radar import (
    MARKET_OPPORTUNITY_RADAR_VERSION,
    MarketMovementTrigger,
    MarketTradeObservation,
)


SIGNAL_PLANE_EPISODE_BRIDGE_VERSION = "signal_plane_episode_bridge_v0"


@dataclass(frozen=True)
class SignalPlaneEpisodeAssignment:
    trigger_key: str
    token_mint: str
    trigger_kind: str
    direction: str
    chain_time: int
    observed_at: int
    method_version: str
    venue: str


def _required(value: str | None, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _episode_venue_and_prefix(
    observation: MarketTradeObservation,
) -> tuple[str, str]:
    venue = _required(observation.venue, "observation venue").lower()
    if venue in {"pump", "pump_bonding_curve", "pumpfun", "pump.fun"}:
        return "pump_bonding_curve", "market-radar:pump"
    if venue in {"pumpswap", "pump_swap"}:
        return "pump_swap", "market-radar:pumpswap-v3"
    raise ValueError(f"unsupported Signal Plane episode venue: {observation.venue!r}")


def build_signal_plane_episode_assignment(
    *,
    trigger: MarketMovementTrigger,
    observation: MarketTradeObservation,
) -> SignalPlaneEpisodeAssignment:
    """Map one Rust/Python Radar trigger to the frozen historical episode identity.

    The live Signal Plane computes the same MarketMovementTrigger semantics as the
    historical Pump/PumpSwap Radar bridges. This adapter intentionally preserves
    their durable episode-assignment contract instead of inventing new episode keys.

    A trigger is emitted only from a trade observation; lifecycle observations never
    become episode triggers by themselves.
    """

    token_mint = _required(observation.token_mint, "observation token_mint")
    if _required(trigger.token_mint, "trigger token_mint") != token_mint:
        raise ValueError("trigger token_mint does not match observation token_mint")
    if trigger.as_of != observation.observed_at:
        raise ValueError("trigger as_of does not match observation observed_at")
    if trigger.method_version != MARKET_OPPORTUNITY_RADAR_VERSION:
        raise ValueError(
            "trigger method_version does not match frozen Market Radar version"
        )
    if observation.chain_time < 0 or observation.observed_at < 0:
        raise ValueError("observation clocks must be non-negative")

    transaction_key = _required(
        observation.transaction_key,
        "observation transaction_key",
    )
    durable_venue, prefix = _episode_venue_and_prefix(observation)

    return SignalPlaneEpisodeAssignment(
        trigger_key=f"{prefix}:{transaction_key}:{token_mint}",
        token_mint=token_mint,
        trigger_kind=_required(trigger.trigger_kind, "trigger_kind"),
        direction=_required(trigger.direction, "direction"),
        chain_time=int(observation.chain_time),
        observed_at=int(observation.observed_at),
        method_version=trigger.method_version,
        venue=durable_venue,
    )


def assign_signal_plane_trigger_episode(
    *,
    acquisition_run_key: str,
    trigger: MarketMovementTrigger,
    observation: MarketTradeObservation,
) -> MarketOpportunityEpisode:
    assignment = build_signal_plane_episode_assignment(
        trigger=trigger,
        observation=observation,
    )
    return assign_market_opportunity_trigger(
        acquisition_run_key=_required(
            acquisition_run_key,
            "acquisition_run_key",
        ),
        trigger_key=assignment.trigger_key,
        token_mint=assignment.token_mint,
        trigger_kind=assignment.trigger_kind,
        direction=assignment.direction,
        chain_time=assignment.chain_time,
        observed_at=assignment.observed_at,
        method_version=assignment.method_version,
        venue=assignment.venue,
    )
