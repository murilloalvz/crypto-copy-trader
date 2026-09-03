import time
from dataclasses import dataclass

from src.market_observation_store import load_market_trades
from src.market_opportunity_episode_store import (
    MarketOpportunityEpisode,
    assign_market_opportunity_trigger,
)
from src.market_opportunity_radar import (
    MarketMovementTrigger,
    MarketRadarConfig,
    detect_market_movement,
)
from src.pumpswap_stream import (
    PumpSwapLogNotification,
    PumpSwapPersistResult,
    PumpSwapPoolResolver,
    persist_pumpswap_notification,
)


@dataclass(frozen=True)
class PumpSwapRadarBridgeHit:
    token_mint: str
    trigger: MarketMovementTrigger
    episode: MarketOpportunityEpisode


@dataclass(frozen=True)
class PumpSwapRadarBridgeResult:
    signature: str
    observed_at: int
    persist_result: PumpSwapPersistResult
    affected_tokens: tuple[str, ...]
    hits: tuple[PumpSwapRadarBridgeHit, ...]


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _evaluate_pumpswap_token(
    *,
    acquisition_run_key: str,
    token_mint: str,
    as_of: int,
    trigger_key: str,
    trigger_chain_time: int,
    config: MarketRadarConfig,
) -> PumpSwapRadarBridgeHit | None:
    """Evaluate PumpSwap flow without treating pool creation as token birth.

    A PumpSwap CreatePoolEvent describes a venue/pool lifecycle transition, not necessarily the
    creation of the token itself. Passing it to the radar's ``fresh_market_burst`` branch would
    incorrectly make migrated/older tokens look newly launched. PumpSwap therefore contributes
    flow to the shared market store and uses the established activity-acceleration branch here.
    Pump bonding CreateEvent remains the canonical fresh-token lifecycle source in v1.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    mint = _required(token_mint, "token_mint")
    raw_trigger_key = _required(trigger_key, "trigger_key")
    if as_of < 0 or trigger_chain_time < 0 or trigger_chain_time > as_of:
        raise ValueError("invalid PumpSwap radar bridge timestamps")

    lower = max(0, as_of - config.baseline_horizon_seconds)
    stored = load_market_trades(
        acquisition_run_key=run_key,
        token_mint=mint,
        as_of=as_of,
        chain_time_after=lower,
    )
    trigger = detect_market_movement(
        [item.observation for item in stored],
        token_mint=mint,
        as_of=as_of,
        lifecycle=None,
        config=config,
    )
    if trigger is None:
        return None

    episode = assign_market_opportunity_trigger(
        acquisition_run_key=run_key,
        trigger_key=raw_trigger_key,
        token_mint=mint,
        trigger_kind=trigger.trigger_kind,
        direction=trigger.direction,
        chain_time=trigger_chain_time,
        observed_at=as_of,
        method_version=trigger.method_version,
        venue="pump_swap",
    )
    return PumpSwapRadarBridgeHit(token_mint=mint, trigger=trigger, episode=episode)


async def process_pumpswap_notification_for_radar(
    notification: PumpSwapLogNotification,
    *,
    acquisition_run_key: str,
    resolver: PumpSwapPoolResolver,
    config: MarketRadarConfig = MarketRadarConfig(),
) -> PumpSwapRadarBridgeResult:
    """Persist one PumpSwap notification and feed its resolved token flow into the shared radar.

    Expensive identity hydration happens before evaluation. The evaluation clock is advanced to
    the time at which pool identity is actually available, so a trade never receives a fake early
    T0 merely because its log arrived before ``pool -> base_mint`` was resolved.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    if resolver.acquisition_run_key != run_key:
        raise ValueError("resolver acquisition_run_key must match bridge run")

    persist_result = await persist_pumpswap_notification(
        notification,
        acquisition_run_key=run_key,
        resolver=resolver,
    )

    evaluation_as_of = max(notification.observed_at, int(time.time()))
    by_token: dict[str, list[int]] = {}
    for event in notification.trade_events:
        mapping = await resolver.resolve(event.pool, as_of=evaluation_as_of)
        if mapping is None:
            continue
        evaluation_as_of = max(evaluation_as_of, mapping.observed_at)
        by_token.setdefault(mapping.base_mint, []).append(event.timestamp)

    hits: list[PumpSwapRadarBridgeHit] = []
    for mint in sorted(by_token):
        hit = _evaluate_pumpswap_token(
            acquisition_run_key=run_key,
            token_mint=mint,
            as_of=evaluation_as_of,
            trigger_key=f"market-radar:pumpswap:{notification.signature}:{mint}",
            trigger_chain_time=max(by_token[mint]),
            config=config,
        )
        if hit is not None:
            hits.append(hit)

    return PumpSwapRadarBridgeResult(
        signature=notification.signature,
        observed_at=evaluation_as_of,
        persist_result=persist_result,
        affected_tokens=tuple(sorted(by_token)),
        hits=tuple(hits),
    )
