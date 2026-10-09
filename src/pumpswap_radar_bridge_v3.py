from dataclasses import dataclass

from src.market_opportunity_radar import MarketRadarConfig
from src.market_transaction_view import load_market_trades_by_transaction
from src.pumpswap_normalized_persistence import (
    PumpSwapNormalizedPersistResult,
    persist_pumpswap_notification_normalized,
)
from src.pumpswap_radar_bridge_v2 import PumpSwapRadarBridgeV2Hit, _evaluate_token
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapPoolResolver


@dataclass(frozen=True)
class PumpSwapRadarBridgeV3Result:
    signature: str
    observed_at: int
    persist_result: PumpSwapNormalizedPersistResult
    affected_tokens: tuple[str, ...]
    hits: tuple[PumpSwapRadarBridgeV2Hit, ...]


def evaluate_persisted_pumpswap_notification_for_radar_v3(
    notification: PumpSwapLogNotification,
    *,
    acquisition_run_key: str,
    persist_result: PumpSwapNormalizedPersistResult,
    config: MarketRadarConfig = MarketRadarConfig(),
) -> PumpSwapRadarBridgeV3Result:
    """Evaluate one already-persisted PumpSwap notification without identity I/O.

    This split lets pool resolution/persistence run concurrently while a coordinator preserves
    notification ingress order for radar/episode assignment. As-of filtering in the market store
    keeps later-persisted observations invisible to an earlier causal evaluation boundary.
    """

    run_key = str(acquisition_run_key).strip()
    if not run_key:
        raise ValueError("acquisition_run_key cannot be empty")

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
        rows = by_token[mint]
        token_as_of = max(observed_at for _, observed_at in rows)
        bridge_observed_at = max(bridge_observed_at, token_as_of)
        hit = _evaluate_token(
            acquisition_run_key=run_key,
            token_mint=mint,
            as_of=token_as_of,
            trigger_key=f"market-radar:pumpswap-v3:{notification.signature}:{mint}",
            trigger_chain_time=max(chain_time for chain_time, _ in rows),
            config=config,
        )
        if hit is not None:
            hits.append(hit)

    return PumpSwapRadarBridgeV3Result(
        signature=notification.signature,
        observed_at=bridge_observed_at,
        persist_result=persist_result,
        affected_tokens=tuple(sorted(by_token)),
        hits=tuple(hits),
    )


async def process_pumpswap_notification_for_radar_v3(
    notification: PumpSwapLogNotification,
    *,
    acquisition_run_key: str,
    resolver: PumpSwapPoolResolver,
    config: MarketRadarConfig = MarketRadarConfig(),
) -> PumpSwapRadarBridgeV3Result:
    """Compatibility path: normalize/persist once and immediately evaluate that transaction."""

    run_key = str(acquisition_run_key).strip()
    if not run_key:
        raise ValueError("acquisition_run_key cannot be empty")
    if resolver.acquisition_run_key != run_key:
        raise ValueError("resolver acquisition_run_key must match bridge run")

    persist_result = await persist_pumpswap_notification_normalized(
        notification,
        acquisition_run_key=run_key,
        resolver=resolver,
    )
    return evaluate_persisted_pumpswap_notification_for_radar_v3(
        notification,
        acquisition_run_key=run_key,
        persist_result=persist_result,
        config=config,
    )
