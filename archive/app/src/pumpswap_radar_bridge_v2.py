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
from src.market_transaction_view import load_market_trades_by_transaction
from src.pumpswap_stream import (
    PumpSwapLogNotification,
    PumpSwapPersistResult,
    PumpSwapPoolResolver,
    persist_pumpswap_notification,
)


@dataclass(frozen=True)
class PumpSwapRadarBridgeV2Hit:
    token_mint: str
    trigger: MarketMovementTrigger
    episode: MarketOpportunityEpisode


@dataclass(frozen=True)
class PumpSwapRadarBridgeV2Result:
    signature: str
    observed_at: int
    persist_result: PumpSwapPersistResult
    affected_tokens: tuple[str, ...]
    hits: tuple[PumpSwapRadarBridgeV2Hit, ...]


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _evaluate_token(
    *,
    acquisition_run_key: str,
    token_mint: str,
    as_of: int,
    trigger_key: str,
    trigger_chain_time: int,
    config: MarketRadarConfig,
) -> PumpSwapRadarBridgeV2Hit | None:
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
    return PumpSwapRadarBridgeV2Hit(token_mint=mint, trigger=trigger, episode=episode)


async def process_pumpswap_notification_for_radar_v2(
    notification: PumpSwapLogNotification,
    *,
    acquisition_run_key: str,
    resolver: PumpSwapPoolResolver,
    config: MarketRadarConfig = MarketRadarConfig(),
) -> PumpSwapRadarBridgeV2Result:
    """Persist once, then derive radar identity from the persisted transaction rows.

    Pool resolution is an acquisition concern. Once persistence has resolved and written a trade,
    the radar bridge must not call the resolver again. This keeps identity availability causal and
    prevents budget-exhausted pools from being retried solely for radar bookkeeping.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    if resolver.acquisition_run_key != run_key:
        raise ValueError("resolver acquisition_run_key must match bridge run")

    persist_result = await persist_pumpswap_notification(
        notification,
        acquisition_run_key=run_key,
        resolver=resolver,
    )

    transaction_rows = load_market_trades_by_transaction(
        acquisition_run_key=run_key,
        transaction_key=notification.signature,
    )

    by_token: dict[str, list[tuple[int, int]]] = {}
    for item in transaction_rows:
        observation = item.observation
        if observation.venue != "pumpswap":
            continue
        by_token.setdefault(observation.token_mint, []).append(
            (observation.chain_time, observation.observed_at)
        )

    hits: list[PumpSwapRadarBridgeV2Hit] = []
    bridge_observed_at = notification.observed_at
    for mint in sorted(by_token):
        chain_times = [item[0] for item in by_token[mint]]
        availability_times = [item[1] for item in by_token[mint]]
        token_as_of = max(availability_times)
        bridge_observed_at = max(bridge_observed_at, token_as_of)
        hit = _evaluate_token(
            acquisition_run_key=run_key,
            token_mint=mint,
            as_of=token_as_of,
            trigger_key=f"market-radar:pumpswap:{notification.signature}:{mint}",
            trigger_chain_time=max(chain_times),
            config=config,
        )
        if hit is not None:
            hits.append(hit)

    return PumpSwapRadarBridgeV2Result(
        signature=notification.signature,
        observed_at=bridge_observed_at,
        persist_result=persist_result,
        affected_tokens=tuple(sorted(by_token)),
        hits=tuple(hits),
    )
