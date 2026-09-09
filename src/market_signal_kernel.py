from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass

from src.market_opportunity_radar import (
    MARKET_OPPORTUNITY_RADAR_VERSION,
    MarketLifecycleObservation,
    MarketMovementFeatures,
    MarketMovementTrigger,
    MarketRadarConfig,
    MarketTradeObservation,
    _coverage_pct,
    _median,
    _validate_config,
    _validate_lifecycle,
    _validate_trade,
)

MARKET_SIGNAL_KERNEL_VERSION = "indexed_market_signal_kernel_v1"
PUMP_LIFECYCLE_VENUES = {"pump", "pump_bonding_curve", "pumpfun", "pump.fun"}


@dataclass(frozen=True)
class MarketSignalKernelStats:
    trade_events_ingested: int
    lifecycle_events_ingested: int
    late_chain_time_inserts: int
    compactions: int
    tracked_assets: int
    retained_trade_rows: int


def _uses_lifecycle(trade: MarketTradeObservation) -> bool:
    return (trade.venue or "").strip().lower() in PUMP_LIFECYCLE_VENUES


def _is_pump_lifecycle(item: MarketLifecycleObservation) -> bool:
    return (item.venue or "").strip().lower() in PUMP_LIFECYCLE_VENUES


def _build_features_from_indexed_windows(
    fast: list[MarketTradeObservation],
    *,
    baseline_count: int,
    token_mint: str,
    as_of: int,
    lifecycle: MarketLifecycleObservation | None,
    config: MarketRadarConfig,
) -> MarketMovementFeatures:
    """Build the frozen Radar v1.1 feature set from preselected causal windows.

    Detailed feature work is required only for the 30-second fast window. The older
    270-second baseline contributes only its event count/rate to the frozen detector,
    so the kernel supplies that count from indexed boundaries instead of rescanning all
    retained rows on every decision.
    """
    buys = [item for item in fast if item.side == "buy"]
    sells = [item for item in fast if item.side == "sell"]

    wallet_rows = [item for item in fast if item.wallet_address is not None]
    unique_wallets = {str(item.wallet_address) for item in wallet_rows}
    wallet_coverage = _coverage_pct(len(wallet_rows), len(fast))

    transaction_rows = [item for item in fast if item.transaction_key is not None]
    unique_transactions = {str(item.transaction_key) for item in transaction_rows}
    transaction_coverage = _coverage_pct(len(transaction_rows), len(fast))
    unique_transaction_count = len(unique_transactions) if transaction_rows else None

    notional_rows = [item for item in fast if item.notional_usd is not None]
    notional_coverage = _coverage_pct(len(notional_rows), len(fast))
    notionals_complete = bool(fast) and len(notional_rows) == len(fast)
    signed_notional_imbalance = None
    if notionals_complete:
        buy_notional = sum(float(item.notional_usd) for item in buys)
        sell_notional = sum(float(item.notional_usd) for item in sells)
        total_notional = buy_notional + sell_notional
        if total_notional > 0:
            signed_notional_imbalance = 100.0 * (buy_notional - sell_notional) / total_notional

    count_imbalance = None
    if fast:
        count_imbalance = 100.0 * (len(buys) - len(sells)) / len(fast)

    pressure = signed_notional_imbalance if signed_notional_imbalance is not None else count_imbalance
    if pressure is None:
        direction = "unknown_pressure"
    elif pressure >= config.pressure_threshold_pct:
        direction = "upward_pressure"
    elif pressure <= -config.pressure_threshold_pct:
        direction = "downward_pressure"
    else:
        direction = "mixed_pressure"

    price_rows = [item for item in fast if item.price_usd is not None]
    price_coverage = _coverage_pct(len(price_rows), len(fast))
    prices_complete = bool(fast) and len(price_rows) == len(fast)
    first_price = float(fast[0].price_usd) if prices_complete else None
    last_price = float(fast[-1].price_usd) if prices_complete else None
    fast_return = None
    if first_price is not None and last_price is not None and len(fast) >= 2:
        fast_return = 100.0 * (last_price / first_price - 1.0)

    fast_rate = len(fast) / config.fast_window_seconds
    baseline_duration = config.baseline_horizon_seconds - config.fast_window_seconds
    baseline_rate = baseline_count / baseline_duration if baseline_count else None
    acceleration = None
    if baseline_rate is not None and baseline_rate > 0:
        acceleration = fast_rate / baseline_rate

    market_age = None
    quality: list[str] = []
    if lifecycle is not None:
        if lifecycle.observed_at <= as_of and lifecycle.market_started_at <= as_of:
            market_age = as_of - lifecycle.market_started_at
        else:
            quality.append("lifecycle_not_available_by_as_of")
    else:
        quality.append("lifecycle_missing")

    if fast and len(wallet_rows) < len(fast):
        quality.append("partial_wallet_identity_coverage")
    if fast and not transaction_rows:
        quality.append("transaction_identity_missing")
    elif fast and len(transaction_rows) < len(fast):
        quality.append("partial_transaction_identity_coverage")
    if fast and not notionals_complete:
        quality.append("partial_notional_coverage")
    if fast and not prices_complete:
        quality.append("partial_price_coverage")
    if not fast:
        quality.append("no_fast_window_events")
    if baseline_count < config.min_baseline_events:
        quality.append("baseline_activity_insufficient")

    lags = [item.observed_at - item.chain_time for item in fast]
    venues = tuple(sorted({str(item.venue) for item in fast if item.venue is not None}))

    return MarketMovementFeatures(
        token_mint=token_mint,
        as_of=as_of,
        fast_window_seconds=config.fast_window_seconds,
        baseline_horizon_seconds=config.baseline_horizon_seconds,
        fast_event_count=len(fast),
        baseline_event_count=baseline_count,
        fast_buy_count=len(buys),
        fast_sell_count=len(sells),
        fast_unique_wallet_count=len(unique_wallets),
        fast_unique_transaction_count=unique_transaction_count,
        wallet_identity_coverage_pct=wallet_coverage,
        transaction_identity_coverage_pct=transaction_coverage,
        notional_coverage_pct=notional_coverage,
        price_coverage_pct=price_coverage,
        fast_event_rate_per_second=fast_rate,
        baseline_event_rate_per_second=baseline_rate,
        activity_acceleration_ratio=acceleration,
        signed_notional_imbalance_pct=signed_notional_imbalance,
        count_imbalance_pct=count_imbalance,
        direction=direction,
        first_price_usd=first_price,
        last_price_usd=last_price,
        fast_return_pct=fast_return,
        median_observation_lag_seconds=_median(lags),
        max_observation_lag_seconds=max(lags) if lags else None,
        venues=venues,
        market_age_seconds=market_age,
        data_quality_flags=tuple(quality),
    )


def _detect_from_indexed_windows(
    fast: list[MarketTradeObservation],
    *,
    baseline_count: int,
    token_mint: str,
    as_of: int,
    lifecycle: MarketLifecycleObservation | None,
    config: MarketRadarConfig,
) -> MarketMovementTrigger | None:
    features = _build_features_from_indexed_windows(
        fast,
        baseline_count=baseline_count,
        token_mint=token_mint,
        as_of=as_of,
        lifecycle=lifecycle,
        config=config,
    )

    breadth_ready = features.fast_unique_wallet_count >= config.min_unique_wallets
    fast_ready = features.fast_event_count >= config.min_fast_events

    transaction_breadth_ready = True
    if features.transaction_identity_coverage_pct == 100.0:
        transaction_breadth_ready = (
            features.fast_unique_transaction_count is not None
            and features.fast_unique_transaction_count >= config.min_unique_transactions
        )

    established_ready = (
        fast_ready
        and breadth_ready
        and transaction_breadth_ready
        and features.baseline_event_count >= config.min_baseline_events
        and features.activity_acceleration_ratio is not None
        and features.activity_acceleration_ratio >= config.min_activity_acceleration_ratio
    )
    fresh_ready = (
        fast_ready
        and breadth_ready
        and transaction_breadth_ready
        and features.market_age_seconds is not None
        and 0 <= features.market_age_seconds <= config.fresh_market_max_age_seconds
    )

    if established_ready:
        trigger_kind = "activity_acceleration"
    elif fresh_ready:
        trigger_kind = "fresh_market_burst"
    else:
        return None

    return MarketMovementTrigger(
        token_mint=features.token_mint,
        as_of=features.as_of,
        method_version=MARKET_OPPORTUNITY_RADAR_VERSION,
        trigger_kind=trigger_kind,
        direction=features.direction,
        features=features,
    )


class IndexedMarketSignalKernel:
    """Bounded memory-first state for the frozen Market Opportunity Radar.

    Contract:
    - inputs are validated once on ingress;
    - same-asset `observed_at` is non-decreasing;
    - chain-time disorder is allowed and inserted causally;
    - only the detector's 300-second horizon is retained;
    - thresholds and method version come directly from the frozen Radar config/version.

    This class performs no persistence, network I/O, enrichment, or async work.
    """

    def __init__(self, config: MarketRadarConfig = MarketRadarConfig()) -> None:
        _validate_config(config)
        self.config = config
        self._rows: dict[str, list[tuple[int, int, int, MarketTradeObservation]]] = defaultdict(list)
        self._lifecycle: dict[str, MarketLifecycleObservation] = {}
        self._last_observed_at: dict[str, int] = {}
        self._sequence = 0
        self._trade_events_ingested = 0
        self._lifecycle_events_ingested = 0
        self._late_chain_time_inserts = 0
        self._compactions = 0

    def ingest_lifecycle(self, item: MarketLifecycleObservation) -> None:
        _validate_lifecycle(item)
        self._lifecycle_events_ingested += 1
        if not _is_pump_lifecycle(item):
            return
        current = self._lifecycle.get(item.token_mint)
        if current is None or item.observed_at >= current.observed_at:
            self._lifecycle[item.token_mint] = item

    def ingest_trade(self, trade: MarketTradeObservation) -> MarketMovementTrigger | None:
        _validate_trade(trade)
        previous_observed = self._last_observed_at.get(trade.token_mint)
        if previous_observed is not None and trade.observed_at < previous_observed:
            raise ValueError("same-asset observed_at regression")
        self._last_observed_at[trade.token_mint] = trade.observed_at

        sequence = self._sequence
        self._sequence += 1
        self._trade_events_ingested += 1

        rows = self._rows[trade.token_mint]
        item = (trade.chain_time, trade.observed_at, sequence, trade)
        if not rows or rows[-1][:3] <= item[:3]:
            rows.append(item)
        else:
            self._late_chain_time_inserts += 1
            keys = [row[:3] for row in rows]
            index = bisect.bisect_right(keys, item[:3])
            rows.insert(index, item)

        baseline_lower = trade.observed_at - self.config.baseline_horizon_seconds
        chain_keys = [row[0] for row in rows]
        prune_to = bisect.bisect_right(chain_keys, baseline_lower)
        if prune_to:
            del rows[:prune_to]
            self._compactions += 1
            chain_keys = chain_keys[prune_to:]

        fast_lower = trade.observed_at - self.config.fast_window_seconds
        fast_start = bisect.bisect_right(chain_keys, fast_lower)
        fast_end = bisect.bisect_right(chain_keys, trade.observed_at)
        baseline_count = fast_start
        fast = [row[3] for row in rows[fast_start:fast_end]]

        lifecycle = self._lifecycle.get(trade.token_mint) if _uses_lifecycle(trade) else None
        return _detect_from_indexed_windows(
            fast,
            baseline_count=baseline_count,
            token_mint=trade.token_mint,
            as_of=trade.observed_at,
            lifecycle=lifecycle,
            config=self.config,
        )

    def stats(self) -> MarketSignalKernelStats:
        return MarketSignalKernelStats(
            trade_events_ingested=self._trade_events_ingested,
            lifecycle_events_ingested=self._lifecycle_events_ingested,
            late_chain_time_inserts=self._late_chain_time_inserts,
            compactions=self._compactions,
            tracked_assets=len(self._rows),
            retained_trade_rows=sum(len(rows) for rows in self._rows.values()),
        )
