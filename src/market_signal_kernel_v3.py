from __future__ import annotations

import bisect
from dataclasses import asdict

from src.market_opportunity_radar import (
    MARKET_OPPORTUNITY_RADAR_VERSION,
    MarketMovementFeatures,
    MarketMovementTrigger,
    MarketRadarConfig,
    MarketTradeObservation,
    _coverage_pct,
    _validate_trade,
)
from src.market_signal_kernel import (
    IndexedMarketSignalKernel,
    _uses_lifecycle,
)


MARKET_SIGNAL_KERNEL_V3_VERSION = "indexed_market_signal_kernel_v3_single_pass_windows"
_INF = float("inf")


def _build_features_single_pass_v3(
    fast: list[MarketTradeObservation],
    *,
    baseline_count: int,
    token_mint: str,
    as_of: int,
    chain_as_of: int,
    lifecycle,
    config: MarketRadarConfig,
) -> MarketMovementFeatures:
    buy_count = 0
    sell_count = 0
    wallet_known = 0
    transaction_known = 0
    notional_known = 0
    price_known = 0
    unique_wallets: set[str] = set()
    unique_transactions: set[str] = set()
    venues: set[str] = set()
    buy_notionals: list[float] = []
    sell_notionals: list[float] = []
    chain_clock_ahead = False

    for item in fast:
        if item.side == "buy":
            buy_count += 1
        else:
            sell_count += 1

        if item.wallet_address is not None:
            wallet_known += 1
            unique_wallets.add(str(item.wallet_address))
        if item.transaction_key is not None:
            transaction_known += 1
            unique_transactions.add(str(item.transaction_key))
        if item.notional_usd is not None:
            notional_known += 1
            # Preserve V2 arithmetic semantics exactly. In CPython 3.12+ builtin
            # sum(float_iterable) uses an improved float summation path, while a
            # manual += accumulator can differ by a few ulps. V68/Signal Plane
            # parity is intentionally bit-for-bit, so retain the per-side order
            # from V2 and delegate the actual reduction to builtin sum().
            if item.side == "buy":
                buy_notionals.append(float(item.notional_usd))
            else:
                sell_notionals.append(float(item.notional_usd))
        if item.price_usd is not None:
            price_known += 1
        if item.venue is not None:
            venues.add(str(item.venue))
        if item.chain_time > item.observed_at:
            chain_clock_ahead = True

    total = len(fast)
    wallet_coverage = _coverage_pct(wallet_known, total)
    transaction_coverage = _coverage_pct(transaction_known, total)
    unique_transaction_count = len(unique_transactions) if transaction_known else None
    notional_coverage = _coverage_pct(notional_known, total)
    notionals_complete = bool(fast) and notional_known == total

    signed_notional_imbalance = None
    if notionals_complete:
        buy_notional = sum(buy_notionals)
        sell_notional = sum(sell_notionals)
        total_notional = buy_notional + sell_notional
        if total_notional > 0:
            signed_notional_imbalance = 100.0 * (buy_notional - sell_notional) / total_notional

    count_imbalance = None
    if fast:
        count_imbalance = 100.0 * (buy_count - sell_count) / total

    pressure = signed_notional_imbalance if signed_notional_imbalance is not None else count_imbalance
    if pressure is None:
        direction = "unknown_pressure"
    elif pressure >= config.pressure_threshold_pct:
        direction = "upward_pressure"
    elif pressure <= -config.pressure_threshold_pct:
        direction = "downward_pressure"
    else:
        direction = "mixed_pressure"

    price_coverage = _coverage_pct(price_known, total)
    prices_complete = bool(fast) and price_known == total
    first_price = float(fast[0].price_usd) if prices_complete else None
    last_price = float(fast[-1].price_usd) if prices_complete else None
    fast_return = None
    if first_price is not None and last_price is not None and total >= 2:
        fast_return = 100.0 * (last_price / first_price - 1.0)

    fast_rate = total / config.fast_window_seconds
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

    if fast and wallet_known < total:
        quality.append("partial_wallet_identity_coverage")
    if fast and not transaction_known:
        quality.append("transaction_identity_missing")
    elif fast and transaction_known < total:
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
    if chain_clock_ahead:
        quality.append("chain_clock_ahead_of_local_observation_clock_observed")

    return MarketMovementFeatures(
        token_mint=token_mint,
        as_of=as_of,
        chain_as_of=chain_as_of,
        fast_window_seconds=config.fast_window_seconds,
        baseline_horizon_seconds=config.baseline_horizon_seconds,
        fast_event_count=total,
        baseline_event_count=baseline_count,
        fast_buy_count=buy_count,
        fast_sell_count=sell_count,
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
        venues=tuple(sorted(venues)),
        market_age_seconds=market_age,
        data_quality_flags=tuple(quality),
    )


def _detect_v3(
    fast: list[MarketTradeObservation],
    *,
    baseline_count: int,
    token_mint: str,
    as_of: int,
    chain_as_of: int,
    lifecycle,
    config: MarketRadarConfig,
) -> MarketMovementTrigger | None:
    features = _build_features_single_pass_v3(
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


class IndexedMarketSignalKernelV3(IndexedMarketSignalKernel):
    """Semantic-parity V3 removing repeated key/list scans from V2 ingress."""

    def ingest_trade(self, trade: MarketTradeObservation) -> MarketMovementTrigger | None:
        _validate_trade(trade)
        previous_observed = self._last_observed_at.get(trade.token_mint)
        if previous_observed is not None and trade.observed_at < previous_observed:
            raise ValueError("same-asset observed_at regression")
        self._last_observed_at[trade.token_mint] = trade.observed_at

        previous_chain = self._latest_chain_time.get(trade.token_mint)
        chain_as_of = trade.chain_time if previous_chain is None else max(previous_chain, trade.chain_time)
        self._latest_chain_time[trade.token_mint] = chain_as_of

        sequence = self._sequence
        self._sequence += 1
        self._trade_events_ingested += 1
        rows = self._rows[trade.token_mint]
        item = (trade.chain_time, trade.observed_at, sequence, trade)
        if not rows or rows[-1][:3] <= item[:3]:
            rows.append(item)
        else:
            self._late_chain_time_inserts += 1
            index = bisect.bisect_right(rows, item)
            rows.insert(index, item)

        baseline_lower = chain_as_of - self.config.baseline_horizon_seconds
        prune_to = bisect.bisect_right(rows, (baseline_lower, _INF, _INF))
        if prune_to:
            del rows[:prune_to]
            self._compactions += 1

        fast_lower = chain_as_of - self.config.fast_window_seconds
        fast_start = bisect.bisect_right(rows, (fast_lower, _INF, _INF))
        fast_end = bisect.bisect_right(rows, (chain_as_of, _INF, _INF))
        baseline_count = fast_start
        fast = [row[3] for row in rows[fast_start:fast_end]]
        lifecycle = self._lifecycle.get(trade.token_mint) if _uses_lifecycle(trade) else None
        return _detect_v3(
            fast,
            baseline_count=baseline_count,
            token_mint=trade.token_mint,
            as_of=trade.observed_at,
            chain_as_of=chain_as_of,
            lifecycle=lifecycle,
            config=self.config,
        )


class TriggerRecordingMarketSignalKernelV3(IndexedMarketSignalKernelV3):
    def __init__(self, config: MarketRadarConfig = MarketRadarConfig()) -> None:
        super().__init__(config)
        self.trigger_ledger: list[dict] = []

    def ingest_trade(self, trade: MarketTradeObservation) -> MarketMovementTrigger | None:
        trigger = super().ingest_trade(trade)
        if trigger is not None:
            self.trigger_ledger.append(asdict(trigger))
        return trigger