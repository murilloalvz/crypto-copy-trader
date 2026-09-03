import math
from dataclasses import dataclass


MARKET_OPPORTUNITY_RADAR_VERSION = "market_opportunity_radar_v1"


@dataclass(frozen=True)
class MarketRadarConfig:
    fast_window_seconds: int = 30
    baseline_horizon_seconds: int = 300
    min_fast_events: int = 6
    min_unique_wallets: int = 4
    min_baseline_events: int = 3
    min_activity_acceleration_ratio: float = 3.0
    fresh_market_max_age_seconds: int = 120
    pressure_threshold_pct: float = 20.0


@dataclass(frozen=True)
class MarketTradeObservation:
    token_mint: str
    side: str
    chain_time: int
    observed_at: int
    wallet_address: str | None = None
    notional_usd: float | None = None
    price_usd: float | None = None
    venue: str | None = None


@dataclass(frozen=True)
class MarketLifecycleObservation:
    token_mint: str
    market_started_at: int
    observed_at: int
    venue: str | None = None


@dataclass(frozen=True)
class MarketMovementFeatures:
    token_mint: str
    as_of: int
    fast_window_seconds: int
    baseline_horizon_seconds: int
    fast_event_count: int
    baseline_event_count: int
    fast_buy_count: int
    fast_sell_count: int
    fast_unique_wallet_count: int
    wallet_identity_coverage_pct: float | None
    notional_coverage_pct: float | None
    price_coverage_pct: float | None
    fast_event_rate_per_second: float
    baseline_event_rate_per_second: float | None
    activity_acceleration_ratio: float | None
    signed_notional_imbalance_pct: float | None
    count_imbalance_pct: float | None
    direction: str
    first_price_usd: float | None
    last_price_usd: float | None
    fast_return_pct: float | None
    median_observation_lag_seconds: float | None
    max_observation_lag_seconds: int | None
    venues: tuple[str, ...]
    market_age_seconds: int | None
    data_quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class MarketMovementTrigger:
    token_mint: str
    as_of: int
    method_version: str
    trigger_kind: str
    direction: str
    features: MarketMovementFeatures


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _validate_config(config: MarketRadarConfig) -> None:
    if config.fast_window_seconds <= 0:
        raise ValueError("fast_window_seconds must be positive")
    if config.baseline_horizon_seconds <= config.fast_window_seconds:
        raise ValueError("baseline_horizon_seconds must exceed fast_window_seconds")
    if config.min_fast_events <= 0:
        raise ValueError("min_fast_events must be positive")
    if config.min_unique_wallets <= 0:
        raise ValueError("min_unique_wallets must be positive")
    if config.min_baseline_events <= 0:
        raise ValueError("min_baseline_events must be positive")
    if config.min_activity_acceleration_ratio <= 0:
        raise ValueError("min_activity_acceleration_ratio must be positive")
    if config.fresh_market_max_age_seconds < 0:
        raise ValueError("fresh_market_max_age_seconds must be non-negative")
    if not 0 <= config.pressure_threshold_pct <= 100:
        raise ValueError("pressure_threshold_pct must be between 0 and 100")


def _validate_trade(item: MarketTradeObservation) -> None:
    _required(item.token_mint, "token_mint")
    if item.side not in {"buy", "sell"}:
        raise ValueError("trade side must be buy or sell")
    if item.chain_time < 0 or item.observed_at < 0:
        raise ValueError("trade timestamps must be non-negative")
    if item.observed_at < item.chain_time:
        raise ValueError("trade observed_at cannot precede chain_time")
    if item.wallet_address is not None and not item.wallet_address.strip():
        raise ValueError("wallet_address cannot be blank")
    if item.venue is not None and not item.venue.strip():
        raise ValueError("venue cannot be blank")
    if item.notional_usd is not None and (
        item.notional_usd < 0 or not math.isfinite(item.notional_usd)
    ):
        raise ValueError("notional_usd must be non-negative and finite")
    if item.price_usd is not None and (
        item.price_usd <= 0 or not math.isfinite(item.price_usd)
    ):
        raise ValueError("price_usd must be positive and finite")


def _validate_lifecycle(item: MarketLifecycleObservation) -> None:
    _required(item.token_mint, "lifecycle token_mint")
    if item.market_started_at < 0 or item.observed_at < 0:
        raise ValueError("lifecycle timestamps must be non-negative")
    if item.observed_at < item.market_started_at:
        raise ValueError("lifecycle observed_at cannot precede market_started_at")
    if item.venue is not None and not item.venue.strip():
        raise ValueError("lifecycle venue cannot be blank")


def _coverage_pct(known: int, total: int) -> float | None:
    if total <= 0:
        return None
    return 100.0 * known / total


def _median(values: list[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def build_market_movement_features(
    observations: list[MarketTradeObservation],
    *,
    token_mint: str,
    as_of: int,
    lifecycle: MarketLifecycleObservation | None = None,
    config: MarketRadarConfig = MarketRadarConfig(),
) -> MarketMovementFeatures:
    """Build a causal movement snapshot using market time and availability time.

    `chain_time` decides whether a trade belongs to the market window. `observed_at` proves that
    the collector knew the trade by `as_of`. Late hydration therefore never turns an old trade
    into fresh flow.
    """

    _validate_config(config)
    mint = _required(token_mint, "token_mint")
    if as_of < 0:
        raise ValueError("as_of must be non-negative")

    for item in observations:
        _validate_trade(item)
    if lifecycle is not None:
        _validate_lifecycle(lifecycle)
        if lifecycle.token_mint != mint:
            raise ValueError("lifecycle token does not match requested token")

    known = [
        item
        for item in observations
        if item.token_mint == mint and item.observed_at <= as_of and item.chain_time <= as_of
    ]

    fast_lower = as_of - config.fast_window_seconds
    baseline_lower = as_of - config.baseline_horizon_seconds

    fast = [item for item in known if fast_lower < item.chain_time <= as_of]
    baseline = [item for item in known if baseline_lower < item.chain_time <= fast_lower]
    fast.sort(key=lambda item: (item.chain_time, item.observed_at))

    buys = [item for item in fast if item.side == "buy"]
    sells = [item for item in fast if item.side == "sell"]

    wallet_rows = [item for item in fast if item.wallet_address is not None]
    unique_wallets = {str(item.wallet_address) for item in wallet_rows}
    wallet_coverage = _coverage_pct(len(wallet_rows), len(fast))

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

    pressure = signed_notional_imbalance
    if pressure is None:
        pressure = count_imbalance
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
    baseline_rate = len(baseline) / baseline_duration if baseline else None
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
    if fast and not notionals_complete:
        quality.append("partial_notional_coverage")
    if fast and not prices_complete:
        quality.append("partial_price_coverage")
    if not fast:
        quality.append("no_fast_window_events")
    if len(baseline) < config.min_baseline_events:
        quality.append("baseline_activity_insufficient")

    lags = [item.observed_at - item.chain_time for item in fast]
    venues = tuple(sorted({str(item.venue) for item in fast if item.venue is not None}))

    return MarketMovementFeatures(
        token_mint=mint,
        as_of=as_of,
        fast_window_seconds=config.fast_window_seconds,
        baseline_horizon_seconds=config.baseline_horizon_seconds,
        fast_event_count=len(fast),
        baseline_event_count=len(baseline),
        fast_buy_count=len(buys),
        fast_sell_count=len(sells),
        fast_unique_wallet_count=len(unique_wallets),
        wallet_identity_coverage_pct=wallet_coverage,
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


def detect_market_movement(
    observations: list[MarketTradeObservation],
    *,
    token_mint: str,
    as_of: int,
    lifecycle: MarketLifecycleObservation | None = None,
    config: MarketRadarConfig = MarketRadarConfig(),
) -> MarketMovementTrigger | None:
    """Return a causal acquisition trigger, never an automatic trading decision."""

    features = build_market_movement_features(
        observations,
        token_mint=token_mint,
        as_of=as_of,
        lifecycle=lifecycle,
        config=config,
    )

    breadth_ready = features.fast_unique_wallet_count >= config.min_unique_wallets
    fast_ready = features.fast_event_count >= config.min_fast_events

    established_ready = (
        fast_ready
        and breadth_ready
        and features.baseline_event_count >= config.min_baseline_events
        and features.activity_acceleration_ratio is not None
        and features.activity_acceleration_ratio >= config.min_activity_acceleration_ratio
    )

    fresh_ready = (
        fast_ready
        and breadth_ready
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
