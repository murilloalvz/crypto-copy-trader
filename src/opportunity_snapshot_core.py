import math
from dataclasses import dataclass

from src.causal_quotes import CausalQuoteObservation, validate_causal_quote


OPPORTUNITY_SNAPSHOT_CORE_VERSION = "opportunity_snapshot_core_v1"
DEFAULT_FLOW_WINDOWS_SECONDS = (10, 30, 60, 300)


@dataclass(frozen=True)
class FlowTradeObservation:
    """One token-side flow event with both chain and real observation time.

    ``observed_at`` is the only timestamp used for causal feature availability. ``chain_time``
    is retained for lag/quality analysis, but a historical event discovered later must never be
    treated as if the system knew it at chain time.
    """

    token_mint: str
    side: str
    chain_time: int
    observed_at: int
    wallet_address: str | None = None
    notional_usd: float | None = None
    price_usd: float | None = None


@dataclass(frozen=True)
class FlowWindowFeatures:
    window_seconds: int
    event_count: int
    buy_count: int
    sell_count: int
    unique_buy_wallet_count: int
    unique_sell_wallet_count: int
    buy_notional_usd: float | None
    sell_notional_usd: float | None
    signed_notional_usd: float | None
    notional_imbalance_pct: float | None
    repeated_wallet_event_share_pct: float | None
    first_price_usd: float | None
    last_price_usd: float | None
    return_pct: float | None
    median_observation_lag_seconds: float | None
    data_quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionSurfaceFeatures:
    quote_count: int
    buy_quote_count: int
    sell_quote_count: int
    executable_quote_count: int
    latest_quote_observed_at: int | None
    latest_buy_price_usd: float | None
    latest_sell_price_usd: float | None
    latest_buy_liquidity_usd: float | None
    latest_sell_liquidity_usd: float | None
    latest_buy_price_impact_pct_points: float | None
    latest_sell_price_impact_pct_points: float | None
    latest_buy_router: str | None
    latest_sell_router: str | None
    data_quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class OpportunitySnapshotCoreV1:
    token_mint: str
    as_of: int
    method_version: str
    flow_windows: tuple[FlowWindowFeatures, ...]
    execution: ExecutionSurfaceFeatures
    data_quality_flags: tuple[str, ...]


def _validate_flow_observation(item: FlowTradeObservation) -> None:
    if not item.token_mint.strip():
        raise ValueError("flow token_mint cannot be empty")
    if item.side not in {"buy", "sell"}:
        raise ValueError("flow side must be buy or sell")
    if item.chain_time < 0 or item.observed_at < 0:
        raise ValueError("flow timestamps must be non-negative")
    if item.observed_at < item.chain_time:
        raise ValueError("flow observed_at cannot be earlier than chain_time")
    if item.wallet_address is not None and not item.wallet_address.strip():
        raise ValueError("flow wallet_address cannot be blank")
    if item.notional_usd is not None and (
        item.notional_usd < 0 or not math.isfinite(item.notional_usd)
    ):
        raise ValueError("flow notional_usd must be non-negative and finite")
    if item.price_usd is not None and (
        item.price_usd <= 0 or not math.isfinite(item.price_usd)
    ):
        raise ValueError("flow price_usd must be positive and finite")


def _median(values: list[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def _build_flow_window(
    observations: list[FlowTradeObservation],
    *,
    as_of: int,
    window_seconds: int,
) -> FlowWindowFeatures:
    lower_bound = as_of - window_seconds
    eligible = [
        item
        for item in observations
        if lower_bound < item.observed_at <= as_of
    ]
    eligible.sort(key=lambda item: (item.observed_at, item.chain_time))

    buys = [item for item in eligible if item.side == "buy"]
    sells = [item for item in eligible if item.side == "sell"]
    buy_wallets = {
        item.wallet_address for item in buys if item.wallet_address is not None
    }
    sell_wallets = {
        item.wallet_address for item in sells if item.wallet_address is not None
    }

    notionals_complete = bool(eligible) and all(
        item.notional_usd is not None for item in eligible
    )
    buy_notional = (
        sum(float(item.notional_usd) for item in buys)
        if notionals_complete
        else None
    )
    sell_notional = (
        sum(float(item.notional_usd) for item in sells)
        if notionals_complete
        else None
    )
    signed_notional = (
        buy_notional - sell_notional
        if buy_notional is not None and sell_notional is not None
        else None
    )
    total_notional = (
        buy_notional + sell_notional
        if buy_notional is not None and sell_notional is not None
        else None
    )
    notional_imbalance = (
        100.0 * signed_notional / total_notional
        if signed_notional is not None and total_notional is not None and total_notional > 0
        else None
    )

    wallet_events = [item.wallet_address for item in eligible if item.wallet_address]
    repeated_wallet_share = None
    if wallet_events:
        repeated_count = len(wallet_events) - len(set(wallet_events))
        repeated_wallet_share = 100.0 * repeated_count / len(wallet_events)

    priced = [item for item in eligible if item.price_usd is not None]
    first_price = float(priced[0].price_usd) if priced else None
    last_price = float(priced[-1].price_usd) if priced else None
    return_pct = (
        100.0 * (last_price / first_price - 1.0)
        if first_price is not None and last_price is not None and len(priced) >= 2
        else None
    )

    quality: list[str] = []
    if eligible and not notionals_complete:
        quality.append("partial_notional_coverage")
    if eligible and len(priced) < len(eligible):
        quality.append("partial_price_coverage")
    if eligible and len(wallet_events) < len(eligible):
        quality.append("partial_wallet_identity_coverage")
    if not eligible:
        quality.append("no_flow_events_in_window")

    lags = [item.observed_at - item.chain_time for item in eligible]
    return FlowWindowFeatures(
        window_seconds=window_seconds,
        event_count=len(eligible),
        buy_count=len(buys),
        sell_count=len(sells),
        unique_buy_wallet_count=len(buy_wallets),
        unique_sell_wallet_count=len(sell_wallets),
        buy_notional_usd=buy_notional,
        sell_notional_usd=sell_notional,
        signed_notional_usd=signed_notional,
        notional_imbalance_pct=notional_imbalance,
        repeated_wallet_event_share_pct=repeated_wallet_share,
        first_price_usd=first_price,
        last_price_usd=last_price,
        return_pct=return_pct,
        median_observation_lag_seconds=_median(lags),
        data_quality_flags=tuple(quality),
    )


def build_execution_surface_features(
    quotes: list[CausalQuoteObservation] | tuple[CausalQuoteObservation, ...],
    *,
    token_mint: str,
    as_of: int,
) -> ExecutionSurfaceFeatures:
    if not token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    if as_of < 0:
        raise ValueError("as_of must be non-negative")

    eligible: list[CausalQuoteObservation] = []
    for quote in quotes:
        validate_causal_quote(quote)
        if quote.token_mint != token_mint or quote.observed_at > as_of:
            continue
        eligible.append(quote)
    eligible.sort(key=lambda item: (item.observed_at, item.market_time))

    buys = [item for item in eligible if item.side == "buy"]
    sells = [item for item in eligible if item.side == "sell"]
    latest_buy = buys[-1] if buys else None
    latest_sell = sells[-1] if sells else None

    quality: list[str] = []
    if not eligible:
        quality.append("no_causal_quotes_available")
    if not buys:
        quality.append("buy_quote_unavailable")
    if not sells:
        quality.append("sell_quote_unavailable")
    if eligible and not any(item.executable for item in eligible):
        quality.append("proxy_quotes_only")

    return ExecutionSurfaceFeatures(
        quote_count=len(eligible),
        buy_quote_count=len(buys),
        sell_quote_count=len(sells),
        executable_quote_count=sum(1 for item in eligible if item.executable),
        latest_quote_observed_at=(eligible[-1].observed_at if eligible else None),
        latest_buy_price_usd=(latest_buy.price_usd if latest_buy else None),
        latest_sell_price_usd=(latest_sell.price_usd if latest_sell else None),
        latest_buy_liquidity_usd=(latest_buy.liquidity_usd if latest_buy else None),
        latest_sell_liquidity_usd=(latest_sell.liquidity_usd if latest_sell else None),
        latest_buy_price_impact_pct_points=(
            latest_buy.provider_price_impact_pct_points if latest_buy else None
        ),
        latest_sell_price_impact_pct_points=(
            latest_sell.provider_price_impact_pct_points if latest_sell else None
        ),
        latest_buy_router=(latest_buy.provider_router if latest_buy else None),
        latest_sell_router=(latest_sell.provider_router if latest_sell else None),
        data_quality_flags=tuple(quality),
    )


def build_opportunity_snapshot_core_v1(
    *,
    token_mint: str,
    as_of: int,
    flow_observations: list[FlowTradeObservation]
    | tuple[FlowTradeObservation, ...] = (),
    quotes: list[CausalQuoteObservation] | tuple[CausalQuoteObservation, ...] = (),
    flow_windows_seconds: tuple[int, ...] = DEFAULT_FLOW_WINDOWS_SECONDS,
) -> OpportunitySnapshotCoreV1:
    """Build a score-free, causal T0 feature snapshot for research.

    The function never fetches data and never assigns trading weights. Callers must pass raw
    observations carrying their real ``observed_at``. Future-observed data is ignored even when
    its underlying chain/market timestamp is earlier than ``as_of``.
    """

    if not token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    if as_of < 0:
        raise ValueError("as_of must be non-negative")
    if not flow_windows_seconds or any(item <= 0 for item in flow_windows_seconds):
        raise ValueError("flow windows must be positive")
    if len(set(flow_windows_seconds)) != len(flow_windows_seconds):
        raise ValueError("flow windows must be unique")

    normalized_flow: list[FlowTradeObservation] = []
    for item in flow_observations:
        _validate_flow_observation(item)
        if item.token_mint == token_mint:
            normalized_flow.append(item)

    windows = tuple(
        _build_flow_window(
            normalized_flow,
            as_of=as_of,
            window_seconds=window_seconds,
        )
        for window_seconds in sorted(flow_windows_seconds)
    )
    execution = build_execution_surface_features(
        quotes,
        token_mint=token_mint,
        as_of=as_of,
    )

    quality: list[str] = []
    if not any(item.event_count for item in windows):
        quality.append("no_flow_context")
    if execution.quote_count == 0:
        quality.append("no_execution_context")

    return OpportunitySnapshotCoreV1(
        token_mint=token_mint,
        as_of=as_of,
        method_version=OPPORTUNITY_SNAPSHOT_CORE_VERSION,
        flow_windows=windows,
        execution=execution,
        data_quality_flags=tuple(quality),
    )
