from __future__ import annotations

from dataclasses import dataclass
import time

from src.market_observation_store import load_latest_market_lifecycle, load_market_trades
from src.market_opportunity_episode_store import assign_market_opportunity_trigger
from src.market_opportunity_radar import (
    MarketMovementTrigger,
    MarketRadarConfig,
    detect_market_movement,
)
from src.market_radar_bridge import MarketRadarBridgeHit
from src.pump_batch_persistence import PumpBatchPersistResult
from src.pump_bonding_stream import PumpLogNotification
from src.pump_radar_bridge_v4 import PumpRadarBridgeV4Result


@dataclass(frozen=True)
class PreparedPumpTokenRadarV5:
    token_mint: str
    trigger_chain_time: int
    trigger: MarketMovementTrigger | None


@dataclass(frozen=True)
class PreparedPumpRadarV5:
    signature: str
    observed_at: int
    persist_result: PumpBatchPersistResult
    affected_tokens: tuple[str, ...]
    tokens: tuple[PreparedPumpTokenRadarV5, ...]
    history_read_seconds: float
    lifecycle_read_seconds: float
    detect_seconds: float

    @property
    def db_read_seconds(self) -> float:
        return self.history_read_seconds + self.lifecycle_read_seconds


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def prepare_persisted_pump_notification_for_radar_v5(
    notification: PumpLogNotification,
    *,
    acquisition_run_key: str,
    persist_result: PumpBatchPersistResult,
    config: MarketRadarConfig = MarketRadarConfig(),
) -> PreparedPumpRadarV5:
    """Read/detect a persisted Pump notification without mutating episode state.

    The expensive causal reads and detector compute are safe to overlap across Pump
    notifications because every query is bounded by that notification's observed_at.
    Trigger/episode persistence is deferred to ``finalize_prepared_pump_radar_v5`` so
    callers can restore original Pump ingress order only around the short stateful phase.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
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

    prepared_tokens: list[PreparedPumpTokenRadarV5] = []
    history_read_seconds = 0.0
    lifecycle_read_seconds = 0.0
    detect_seconds = 0.0

    for mint in expected_tokens:
        lower = max(0, notification.observed_at - config.baseline_horizon_seconds)

        phase_started = time.perf_counter()
        stored = load_market_trades(
            acquisition_run_key=run_key,
            token_mint=mint,
            as_of=notification.observed_at,
            chain_time_after=lower,
        )
        history_read_seconds += time.perf_counter() - phase_started

        phase_started = time.perf_counter()
        lifecycle_row = load_latest_market_lifecycle(
            acquisition_run_key=run_key,
            token_mint=mint,
            as_of=notification.observed_at,
            venue="pump_bonding_curve",
        )
        lifecycle_read_seconds += time.perf_counter() - phase_started

        phase_started = time.perf_counter()
        trigger = detect_market_movement(
            [item.observation for item in stored],
            token_mint=mint,
            as_of=notification.observed_at,
            lifecycle=(lifecycle_row.observation if lifecycle_row is not None else None),
            config=config,
        )
        detect_seconds += time.perf_counter() - phase_started

        prepared_tokens.append(
            PreparedPumpTokenRadarV5(
                token_mint=mint,
                trigger_chain_time=max(by_token[mint]),
                trigger=trigger,
            )
        )

    return PreparedPumpRadarV5(
        signature=notification.signature,
        observed_at=notification.observed_at,
        persist_result=persist_result,
        affected_tokens=expected_tokens,
        tokens=tuple(prepared_tokens),
        history_read_seconds=history_read_seconds,
        lifecycle_read_seconds=lifecycle_read_seconds,
        detect_seconds=detect_seconds,
    )


def finalize_prepared_pump_radar_v5(
    prepared: PreparedPumpRadarV5,
    *,
    acquisition_run_key: str,
) -> PumpRadarBridgeV4Result:
    """Persist prepared Pump triggers while preserving the v4 trigger identity."""

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    hits: list[MarketRadarBridgeHit] = []

    for token in prepared.tokens:
        trigger = token.trigger
        if trigger is None:
            continue
        episode = assign_market_opportunity_trigger(
            acquisition_run_key=run_key,
            trigger_key=f"market-radar:pump:{prepared.signature}:{token.token_mint}",
            token_mint=token.token_mint,
            trigger_kind=trigger.trigger_kind,
            direction=trigger.direction,
            chain_time=token.trigger_chain_time,
            observed_at=prepared.observed_at,
            method_version=trigger.method_version,
            venue="pump_bonding_curve",
        )
        hits.append(
            MarketRadarBridgeHit(
                token_mint=token.token_mint,
                trigger=trigger,
                episode=episode,
            )
        )

    return PumpRadarBridgeV4Result(
        signature=prepared.signature,
        observed_at=prepared.observed_at,
        newly_persisted_trades=prepared.persist_result.newly_persisted_trades,
        affected_tokens=prepared.affected_tokens,
        hits=tuple(hits),
    )
