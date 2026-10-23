from dataclasses import dataclass
import time

from src.market_observation_store import load_market_trades
from src.market_opportunity_episode_store import assign_market_opportunity_trigger
from src.market_opportunity_radar import MarketRadarConfig, detect_market_movement
from src.market_transaction_view import load_market_trades_by_transaction
from src.pumpswap_normalized_persistence import PumpSwapNormalizedPersistResult
from src.pumpswap_radar_bridge_v2 import PumpSwapRadarBridgeV2Hit
from src.pumpswap_stream import PumpSwapLogNotification


@dataclass(frozen=True)
class PumpSwapRadarBridgeV4Telemetry:
    token_count: int
    transaction_view_read_seconds: float
    history_read_seconds: float
    detect_seconds: float
    episode_assign_seconds: float

    @property
    def db_read_seconds(self) -> float:
        return self.transaction_view_read_seconds + self.history_read_seconds


@dataclass(frozen=True)
class PumpSwapRadarBridgeV4Result:
    signature: str
    observed_at: int
    persist_result: PumpSwapNormalizedPersistResult
    affected_tokens: tuple[str, ...]
    hits: tuple[PumpSwapRadarBridgeV2Hit, ...]
    telemetry: PumpSwapRadarBridgeV4Telemetry


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def evaluate_persisted_pumpswap_notification_for_radar_v4(
    notification: PumpSwapLogNotification,
    *,
    acquisition_run_key: str,
    persist_result: PumpSwapNormalizedPersistResult,
    config: MarketRadarConfig = MarketRadarConfig(),
) -> PumpSwapRadarBridgeV4Result:
    """Diagnostic-equivalent of the v3 radar bridge with read/compute timing.

    The causal boundary, trigger key, detector config and episode assignment semantics are
    intentionally identical to v3. Timing is observational only and must not affect decisions.
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

    hits: list[PumpSwapRadarBridgeV2Hit] = []
    bridge_observed_at = notification.observed_at
    history_read_seconds = 0.0
    detect_seconds = 0.0
    episode_assign_seconds = 0.0

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
        if trigger is None:
            continue

        phase_started = time.perf_counter()
        episode = assign_market_opportunity_trigger(
            acquisition_run_key=run_key,
            trigger_key=f"market-radar:pumpswap-v3:{notification.signature}:{mint}",
            token_mint=mint,
            trigger_kind=trigger.trigger_kind,
            direction=trigger.direction,
            chain_time=trigger_chain_time,
            observed_at=token_as_of,
            method_version=trigger.method_version,
            venue="pump_swap",
        )
        episode_assign_seconds += time.perf_counter() - phase_started
        hits.append(PumpSwapRadarBridgeV2Hit(token_mint=mint, trigger=trigger, episode=episode))

    return PumpSwapRadarBridgeV4Result(
        signature=notification.signature,
        observed_at=bridge_observed_at,
        persist_result=persist_result,
        affected_tokens=tuple(sorted(by_token)),
        hits=tuple(hits),
        telemetry=PumpSwapRadarBridgeV4Telemetry(
            token_count=len(by_token),
            transaction_view_read_seconds=transaction_view_read_seconds,
            history_read_seconds=history_read_seconds,
            detect_seconds=detect_seconds,
            episode_assign_seconds=episode_assign_seconds,
        ),
    )
