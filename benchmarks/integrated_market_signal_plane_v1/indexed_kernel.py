from __future__ import annotations

import bisect
from collections import defaultdict

from benchmarks.commodity_signal_plane_v0.benchmark import TraceRecord
from benchmarks.integrated_market_signal_plane_v1.optimized_kernel import (
    _coverage_pct,
    _is_pump_lifecycle,
    _uses_lifecycle,
)
from src.market_opportunity_radar import (
    MARKET_OPPORTUNITY_RADAR_VERSION,
    MarketLifecycleObservation,
    MarketMovementFeatures,
    MarketMovementTrigger,
    MarketRadarConfig,
    MarketTradeObservation,
)


def build_features_from_indexed_windows(
    fast: list[MarketTradeObservation],
    *,
    baseline_count: int,
    token_mint: str,
    as_of: int,
    chain_as_of: int,
    lifecycle: MarketLifecycleObservation | None,
    config: MarketRadarConfig,
) -> MarketMovementFeatures:
    """Build Radar features from already-selected chain-time windows.

    ``as_of`` is the local evidence-availability clock. ``chain_as_of`` is the
    monotone Solana/chain-time anchor used for market windows. The two domains are
    deliberately never subtracted to manufacture a latency measurement.
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
        if lifecycle.observed_at > as_of:
            quality.append("lifecycle_not_available_by_as_of")
        elif lifecycle.market_started_at <= chain_as_of:
            market_age = chain_as_of - lifecycle.market_started_at
        else:
            quality.append("lifecycle_started_after_chain_as_of")
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
    if fast:
        quality.append("observation_lag_unavailable_unaligned_clock_domains")
    if any(item.chain_time > item.observed_at for item in fast):
        quality.append("chain_clock_ahead_of_local_observation_clock_observed")

    venues = tuple(sorted({str(item.venue) for item in fast if item.venue is not None}))

    return MarketMovementFeatures(
        token_mint=token_mint,
        as_of=as_of,
        chain_as_of=chain_as_of,
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
        median_observation_lag_seconds=None,
        max_observation_lag_seconds=None,
        venues=venues,
        market_age_seconds=market_age,
        data_quality_flags=tuple(quality),
    )


def detect_from_indexed_windows(
    fast: list[MarketTradeObservation],
    *,
    baseline_count: int,
    token_mint: str,
    as_of: int,
    chain_as_of: int,
    lifecycle: MarketLifecycleObservation | None,
    config: MarketRadarConfig,
) -> MarketMovementTrigger | None:
    features = build_features_from_indexed_windows(
        fast,
        baseline_count=baseline_count,
        token_mint=token_mint,
        as_of=as_of,
        chain_as_of=chain_as_of,
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


class IndexedWindowRadarState:
    """Benchmark candidate using binary-search chain-window boundaries.

    Availability ordering remains local-clock based. Each token carries a monotone
    chain-time anchor equal to the greatest chain timestamp observed so far. Late
    chain-time inserts never move that anchor backwards and cannot become fresh flow.
    """

    def __init__(self, config: MarketRadarConfig = MarketRadarConfig()) -> None:
        self.config = config
        self.rows: dict[str, list[tuple[int, int, int, MarketTradeObservation]]] = defaultdict(list)
        self.lifecycle: dict[str, MarketLifecycleObservation] = {}
        self.last_observed_at: dict[str, int] = {}
        self.latest_chain_time: dict[str, int] = {}
        self.late_chain_time_inserts = 0
        self.compactions = 0

    def _insert_trade(
        self, record: TraceRecord
    ) -> tuple[list[tuple[int, int, int, MarketTradeObservation]], int]:
        assert record.trade is not None
        trade = record.trade
        previous_observed = self.last_observed_at.get(trade.token_mint)
        if previous_observed is not None and trade.observed_at < previous_observed:
            raise ValueError("same-asset observed_at regression")
        self.last_observed_at[trade.token_mint] = trade.observed_at

        previous_chain = self.latest_chain_time.get(trade.token_mint)
        chain_as_of = trade.chain_time if previous_chain is None else max(previous_chain, trade.chain_time)
        self.latest_chain_time[trade.token_mint] = chain_as_of

        rows = self.rows[trade.token_mint]
        item = (trade.chain_time, trade.observed_at, record.sequence, trade)
        if not rows or rows[-1][:3] <= item[:3]:
            rows.append(item)
        else:
            self.late_chain_time_inserts += 1
            keys = [row[:3] for row in rows]
            index = bisect.bisect_right(keys, item[:3])
            rows.insert(index, item)

        cutoff = chain_as_of - self.config.baseline_horizon_seconds
        chain_keys = [row[0] for row in rows]
        prune_to = bisect.bisect_right(chain_keys, cutoff)
        if prune_to:
            del rows[:prune_to]
            self.compactions += 1
        return rows, chain_as_of

    def ingest(self, record: TraceRecord) -> MarketMovementTrigger | None:
        if record.kind == "lifecycle":
            assert record.lifecycle is not None
            if _is_pump_lifecycle(record.lifecycle):
                current = self.lifecycle.get(record.lifecycle.token_mint)
                if current is None or record.lifecycle.observed_at >= current.observed_at:
                    self.lifecycle[record.lifecycle.token_mint] = record.lifecycle
            return None

        assert record.trade is not None
        trade = record.trade
        rows, chain_as_of = self._insert_trade(record)
        chain_keys = [row[0] for row in rows]
        baseline_lower = chain_as_of - self.config.baseline_horizon_seconds
        fast_lower = chain_as_of - self.config.fast_window_seconds
        baseline_start = bisect.bisect_right(chain_keys, baseline_lower)
        fast_start = bisect.bisect_right(chain_keys, fast_lower)
        fast_end = bisect.bisect_right(chain_keys, chain_as_of)
        baseline_count = max(0, fast_start - baseline_start)
        fast = [row[3] for row in rows[fast_start:fast_end]]

        lifecycle = self.lifecycle.get(trade.token_mint) if _uses_lifecycle(trade) else None
        return detect_from_indexed_windows(
            fast,
            baseline_count=baseline_count,
            token_mint=trade.token_mint,
            as_of=trade.observed_at,
            chain_as_of=chain_as_of,
            lifecycle=lifecycle,
            config=self.config,
        )
