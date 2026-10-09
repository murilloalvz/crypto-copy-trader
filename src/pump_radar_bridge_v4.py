from __future__ import annotations

from dataclasses import dataclass

from src.market_radar_bridge import MarketRadarBridgeHit, evaluate_market_token
from src.market_opportunity_radar import MarketRadarConfig
from src.pump_batch_persistence import PumpBatchPersistResult
from src.pump_bonding_stream import PumpLogNotification


@dataclass(frozen=True)
class PumpRadarBridgeV4Result:
    signature: str
    observed_at: int
    newly_persisted_trades: int
    affected_tokens: tuple[str, ...]
    hits: tuple[MarketRadarBridgeHit, ...]


def evaluate_persisted_pump_notification_for_radar_v4(
    notification: PumpLogNotification,
    *,
    acquisition_run_key: str,
    persist_result: PumpBatchPersistResult,
    config: MarketRadarConfig = MarketRadarConfig(),
) -> PumpRadarBridgeV4Result:
    """Evaluate a Pump notification only after its persistence stage completed.

    This function performs no writes for the raw Pump notification itself. It exists so runtime
    orchestration can persist notifications concurrently, reorder completions back to original
    websocket ingress sequence, and only then evaluate the radar. That preserves the same causal
    first-trigger ordering as the sequential bridge while removing persistence from the hot radar
    worker.
    """

    if persist_result.signature != notification.signature:
        raise ValueError("persist_result signature does not match notification")

    by_token: dict[str, list[int]] = {}
    for event in notification.events:
        if event.sol_amount <= 0:
            continue
        by_token.setdefault(event.mint, []).append(event.timestamp)

    expected_tokens = tuple(sorted(by_token))
    if expected_tokens != persist_result.affected_tokens:
        raise ValueError("persist_result affected_tokens do not match notification")

    hits: list[MarketRadarBridgeHit] = []
    for mint in expected_tokens:
        hit = evaluate_market_token(
            acquisition_run_key=acquisition_run_key,
            token_mint=mint,
            as_of=notification.observed_at,
            trigger_key=f"market-radar:pump:{notification.signature}:{mint}",
            trigger_chain_time=max(by_token[mint]),
            venue="pump_bonding_curve",
            config=config,
        )
        if hit is not None:
            hits.append(hit)

    return PumpRadarBridgeV4Result(
        signature=notification.signature,
        observed_at=notification.observed_at,
        newly_persisted_trades=persist_result.newly_persisted_trades,
        affected_tokens=expected_tokens,
        hits=tuple(hits),
    )
