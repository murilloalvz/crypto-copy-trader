from dataclasses import dataclass

from src.market_observation_store import load_latest_market_lifecycle, load_market_trades
from src.market_opportunity_episode_store import (
    MarketOpportunityEpisode,
    assign_market_opportunity_trigger,
)
from src.market_opportunity_radar import MarketRadarConfig, MarketMovementTrigger, detect_market_movement
from src.pump_bonding_stream import PumpLogNotification, persist_pump_notification


@dataclass(frozen=True)
class MarketRadarBridgeHit:
    token_mint: str
    trigger: MarketMovementTrigger
    episode: MarketOpportunityEpisode


@dataclass(frozen=True)
class PumpRadarBridgeResult:
    signature: str
    observed_at: int
    newly_persisted_trades: int
    affected_tokens: tuple[str, ...]
    hits: tuple[MarketRadarBridgeHit, ...]


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def evaluate_market_token(
    *,
    acquisition_run_key: str,
    token_mint: str,
    as_of: int,
    trigger_key: str,
    trigger_chain_time: int,
    venue: str | None,
    config: MarketRadarConfig = MarketRadarConfig(),
) -> MarketRadarBridgeHit | None:
    """Evaluate one token from persisted causal observations and open/reuse an episode.

    This bridge is intentionally acquisition-only. It does not freeze `decision_as_of`, compute a
    trading score or request any execution. Decision freeze belongs to the later enrichment stage.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    mint = _required(token_mint, "token_mint")
    raw_trigger_key = _required(trigger_key, "trigger_key")
    if as_of < 0 or trigger_chain_time < 0:
        raise ValueError("bridge timestamps must be non-negative")
    if trigger_chain_time > as_of:
        raise ValueError("trigger_chain_time cannot exceed as_of")

    lower = max(0, as_of - config.baseline_horizon_seconds)
    stored = load_market_trades(
        acquisition_run_key=run_key,
        token_mint=mint,
        as_of=as_of,
        chain_time_after=lower,
    )
    lifecycle_row = load_latest_market_lifecycle(
        acquisition_run_key=run_key,
        token_mint=mint,
        as_of=as_of,
    )
    trigger = detect_market_movement(
        [item.observation for item in stored],
        token_mint=mint,
        as_of=as_of,
        lifecycle=(lifecycle_row.observation if lifecycle_row is not None else None),
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
        venue=venue,
    )
    return MarketRadarBridgeHit(token_mint=mint, trigger=trigger, episode=episode)


def process_pump_notification_for_radar(
    notification: PumpLogNotification,
    *,
    acquisition_run_key: str,
    config: MarketRadarConfig = MarketRadarConfig(),
) -> PumpRadarBridgeResult:
    """Persist one Pump notification, then evaluate each affected SOL-paired token once.

    Multiple TradeEvents in the same transaction remain raw rows in SQLite, but all carry the same
    transaction signature. The transaction-aware radar can therefore require transaction breadth
    and cannot mistake four events from one signature for four independent transactions.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    newly_persisted = persist_pump_notification(
        notification,
        acquisition_run_key=run_key,
    )

    by_token: dict[str, list[int]] = {}
    for event in notification.events:
        if event.sol_amount <= 0:
            continue
        by_token.setdefault(event.mint, []).append(event.timestamp)

    hits: list[MarketRadarBridgeHit] = []
    for mint in sorted(by_token):
        hit = evaluate_market_token(
            acquisition_run_key=run_key,
            token_mint=mint,
            as_of=notification.observed_at,
            trigger_key=f"market-radar:pump:{notification.signature}:{mint}",
            trigger_chain_time=max(by_token[mint]),
            venue="pump_bonding_curve",
            config=config,
        )
        if hit is not None:
            hits.append(hit)

    return PumpRadarBridgeResult(
        signature=notification.signature,
        observed_at=notification.observed_at,
        newly_persisted_trades=newly_persisted,
        affected_tokens=tuple(sorted(by_token)),
        hits=tuple(hits),
    )
