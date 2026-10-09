from dataclasses import dataclass
import time

from src.market_observation_store import load_market_trades
from src.market_opportunity_episode_store import assign_market_opportunity_trigger
from src.market_opportunity_radar import (
    MarketMovementTrigger,
    MarketRadarConfig,
    detect_market_movement,
)
from src.market_transaction_view import load_market_trades_by_transaction
from src.pumpswap_normalized_persistence import PumpSwapNormalizedPersistResult
from src.pumpswap_radar_bridge_v2 import PumpSwapRadarBridgeV2Hit
from src.pumpswap_radar_bridge_v4 import (
    PumpSwapRadarBridgeV4Result,
    PumpSwapRadarBridgeV4Telemetry,
)
from src.pumpswap_stream import PumpSwapLogNotification


@dataclass(frozen=True)
class PreparedPumpSwapTokenRadarV5:
    token_mint: str
    token_as_of: int
    trigger_chain_time: int
    trigger: MarketMovementTrigger | None


@dataclass(frozen=True)
class PreparedPumpSwapRadarV5:
    signature: str
    observed_at: int
    persist_result: PumpSwapNormalizedPersistResult
    affected_tokens: tuple[str, ...]
    tokens: tuple[PreparedPumpSwapTokenRadarV5, ...]
    transaction_view_read_seconds: float
    history_read_seconds: float
    detect_seconds: float

    @property
    def db_read_seconds(self) -> float:
        return self.transaction_view_read_seconds + self.history_read_seconds


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def prepare_persisted_pumpswap_notification_for_radar_v5(
    notification: PumpSwapLogNotification,
    *,
    acquisition_run_key: str,
    persist_result: PumpSwapNormalizedPersistResult,
    config: MarketRadarConfig = MarketRadarConfig(),
) -> PreparedPumpSwapRadarV5:
    """Read/detect one persisted notification without mutating trigger/episode state.

    Every detector read remains bounded by the persisted observation's causal ``observed_at``.
    This phase is therefore safe to overlap across notifications for the same asset. Episode
    assignment is intentionally deferred to ``finalize_prepared_pumpswap_radar_v5`` so the caller
    can preserve per-asset ingress order only around the stateful commit phase.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")

    started = time.perf_counter()
    transaction_rows = load_market_trades_by_transaction(
        acquisition_run_key=run_key,
        transaction_key=notification.signature,
    )
    transaction_view_read_seconds = time.perf_counter() - started

    by_token: dict[str, list[tuple[int, int]]] = {}
    for item in transaction_rows:
        observation = item.observation
        if observation.venue != "pumpswap":
            continue
        by_token.setdefault(observation.token_mint, []).append(
            (observation.chain_time, observation.observed_at)
        )

    prepared_tokens: list[PreparedPumpSwapTokenRadarV5] = []
    bridge_observed_at = notification.observed_at
    history_read_seconds = 0.0
    detect_seconds = 0.0

    for mint in sorted(by_token):
        rows = by_token[mint]
        token_as_of = max(observed_at for _, observed_at in rows)
        trigger_chain_time = max(chain_time for chain_time, _ in rows)
        if token_as_of < 0 or trigger_chain_time < 0 or trigger_chain_time > token_as_of:
            raise ValueError("invalid PumpSwap radar bridge timestamps")
        bridge_observed_at = max(bridge_observed_at, token_as_of)

        lower = max(0, token_as_of - config.baseline_horizon_seconds)
        phase_started = time.perf_counter()
        stored = load_market_trades(
            acquisition_run_key=run_key,
            token_mint=mint,
            as_of=token_as_of,
            chain_time_after=lower,
        )
        history_read_seconds += time.perf_counter() - phase_started

        phase_started = time.perf_counter()
        trigger = detect_market_movement(
            [item.observation for item in stored],
            token_mint=mint,
            as_of=token_as_of,
            lifecycle=None,
            config=config,
        )
        detect_seconds += time.perf_counter() - phase_started
        prepared_tokens.append(
            PreparedPumpSwapTokenRadarV5(
                token_mint=mint,
                token_as_of=token_as_of,
                trigger_chain_time=trigger_chain_time,
                trigger=trigger,
            )
        )

    return PreparedPumpSwapRadarV5(
        signature=notification.signature,
        observed_at=bridge_observed_at,
        persist_result=persist_result,
        affected_tokens=tuple(sorted(by_token)),
        tokens=tuple(prepared_tokens),
        transaction_view_read_seconds=transaction_view_read_seconds,
        history_read_seconds=history_read_seconds,
        detect_seconds=detect_seconds,
    )


def finalize_prepared_pumpswap_radar_v5(
    prepared: PreparedPumpSwapRadarV5,
    *,
    acquisition_run_key: str,
) -> PumpSwapRadarBridgeV4Result:
    """Assign prepared triggers to episodes.

    Callers must preserve ingress FIFO for notifications sharing an opportunity asset. This is the
    only stateful phase of v5. Trigger keys and episode semantics are identical to the v3/v4 bridge.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    hits: list[PumpSwapRadarBridgeV2Hit] = []
    episode_assign_seconds = 0.0

    for token in prepared.tokens:
        trigger = token.trigger
        if trigger is None:
            continue

        phase_started = time.perf_counter()
        episode = assign_market_opportunity_trigger(
            acquisition_run_key=run_key,
            trigger_key=f"market-radar:pumpswap-v3:{prepared.signature}:{token.token_mint}",
            token_mint=token.token_mint,
            trigger_kind=trigger.trigger_kind,
            direction=trigger.direction,
            chain_time=token.trigger_chain_time,
            observed_at=token.token_as_of,
            method_version=trigger.method_version,
            venue="pump_swap",
        )
        episode_assign_seconds += time.perf_counter() - phase_started
        hits.append(
            PumpSwapRadarBridgeV2Hit(
                token_mint=token.token_mint,
                trigger=trigger,
                episode=episode,
            )
        )

    return PumpSwapRadarBridgeV4Result(
        signature=prepared.signature,
        observed_at=prepared.observed_at,
        persist_result=prepared.persist_result,
        affected_tokens=prepared.affected_tokens,
        hits=tuple(hits),
        telemetry=PumpSwapRadarBridgeV4Telemetry(
            token_count=len(prepared.tokens),
            transaction_view_read_seconds=prepared.transaction_view_read_seconds,
            history_read_seconds=prepared.history_read_seconds,
            detect_seconds=prepared.detect_seconds,
            episode_assign_seconds=episode_assign_seconds,
        ),
    )
