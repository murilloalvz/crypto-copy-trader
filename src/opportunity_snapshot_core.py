import math
from dataclasses import dataclass

from src.causal_quotes import CausalQuoteObservation, validate_causal_quote


OPPORTUNITY_SNAPSHOT_CORE_VERSION = "opportunity_snapshot_core_v1_2_clock_domains"
DEFAULT_FLOW_WINDOWS_SECONDS = (10, 30, 60, 300)


@dataclass(frozen=True)
class FlowTradeObservation:
    """One token-side flow event with independent chain and observation clocks.

    ``chain_time`` is Solana on-chain approximate Unix time. ``observed_at`` is the
    collector-local availability clock. Causal availability uses only
    ``observed_at <= as_of``. Market-window membership uses only ``chain_time``
    against an explicit same-domain ``chain_as_of``.
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
    wallet_identity_coverage_pct: float | None
    notional_coverage_pct: float | None
    price_coverage_pct: float | None
    buy_notional_usd: float | None
    sell_notional_usd: float | None
    signed_notional_usd: float | None
    notional_imbalance_pct: float | None
    repeated_wallet_event_share_pct: float | None
    first_price_usd: float | None
    last_price_usd: float | None
    return_pct: float | None
    median_observation_lag_seconds: float | None
    max_observation_lag_seconds: int | None
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
    latest_buy_observation_age_seconds: int | None
    latest_sell_observation_age_seconds: int | None
    latest_buy_market_age_seconds: int | None
    latest_sell_market_age_seconds: int | None
    quote_notional_min_usd: float | None
    quote_notional_max_usd: float | None
    data_quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class OpportunitySnapshotCoreV1:
    token_mint: str
    as_of: int
    chain_as_of: int | None
    method_version: str
    flow_windows: tuple[FlowWindowFeatures, ...]
    execution: ExecutionSurfaceFeatures
    data_quality_flags: tuple[str, ...]


def _validate_flow_observation(item: FlowTradeObservation) -> None:
    if not item.token_mint.strip():
        raise ValueError("flow token_mint cannot be empty")
    if item.side not in {"buy", "sell"}:
        raise ValueError("flow side must be buy or sell")
    if (
        not isinstance(item.chain_time, int)
        or isinstance(item.chain_time, bool)
        or not isinstance(item.observed_at, int)
        or isinstance(item.observed_at, bool)
        or item.chain_time < 0
        or item.observed_at < 0
    ):
        raise ValueError("flow timestamps must be non-negative integers")
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


def _coverage_pct(known_count: int, total_count: int) -> float | None:
    if total_count <= 0:
        return None
    return 100.0 * known_count / total_count


def _build_flow_window(
    observations: list[FlowTradeObservation],
    *,
    as_of: int,
    chain_as_of: int,
    window_seconds: int,
) -> FlowWindowFeatures:
    lower_bound = chain_as_of - window_seconds
    eligible = [
        item
        for item in observations
        if item.observed_at <= as_of and lower_bound < item.chain_time <= chain_as_of
    ]
    eligible.sort(key=lambda item: (item.chain_time, item.observed_at))

    buys = [item for item in eligible if item.side == "buy"]
    sells = [item for item in eligible if item.side == "sell"]

    wallet_events = [item.wallet_address for item in eligible if item.wallet_address]
    wallet_coverage = _coverage_pct(len(wallet_events), len(eligible))
    buy_wallets = {item.wallet_address for item in buys if item.wallet_address is not None}
    sell_wallets = {item.wallet_address for item in sells if item.wallet_address is not None}

    known_notionals = [item for item in eligible if item.notional_usd is not None]
    notional_coverage = _coverage_pct(len(known_notionals), len(eligible))
    notionals_complete = bool(eligible) and len(known_notionals) == len(eligible)
    buy_notional = sum(float(item.notional_usd) for item in buys) if notionals_complete else None
    sell_notional = sum(float(item.notional_usd) for item in sells) if notionals_complete else None
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

    repeated_wallet_share = None
    if wallet_events and len(wallet_events) == len(eligible):
        repeated_count = len(wallet_events) - len(set(wallet_events))
        repeated_wallet_share = 100.0 * repeated_count / len(wallet_events)

    priced = [item for item in eligible if item.price_usd is not None]
    price_coverage = _coverage_pct(len(priced), len(eligible))
    prices_complete = bool(eligible) and len(priced) == len(eligible)
    first_price = float(eligible[0].price_usd) if prices_complete else None
    last_price = float(eligible[-1].price_usd) if prices_complete else None
    return_pct = (
        100.0 * (last_price / first_price - 1.0)
        if first_price is not None and last_price is not None and len(eligible) >= 2
        else None
    )

    quality: list[str] = []
    if eligible and not notionals_complete:
        quality.append("partial_notional_coverage")
    if eligible and not prices_complete:
        quality.append("partial_price_coverage")
    if eligible and len(wallet_events) < len(eligible):
        quality.append("partial_wallet_identity_coverage")
    if not eligible:
        quality.append("no_flow_events_in_window")
    if eligible:
        quality.append("observation_lag_unavailable_unaligned_clock_domains")
    if any(item.chain_time > item.observed_at for item in eligible):
        quality.append("chain_clock_ahead_of_local_observation_clock_observed")

    return FlowWindowFeatures(
        window_seconds=window_seconds,
        event_count=len(eligible),
        buy_count=len(buys),
        sell_count=len(sells),
        unique_buy_wallet_count=len(buy_wallets),
        unique_sell_wallet_count=len(sell_wallets),
        wallet_identity_coverage_pct=wallet_coverage,
        notional_coverage_pct=notional_coverage,
        price_coverage_pct=price_coverage,
        buy_notional_usd=buy_notional,
        sell_notional_usd=sell_notional,
        signed_notional_usd=signed_notional,
        notional_imbalance_pct=notional_imbalance,
        repeated_wallet_event_share_pct=repeated_wallet_share,
        first_price_usd=first_price,
        last_price_usd=last_price,
        return_pct=return_pct,
        median_observation_lag_seconds=None,
        max_observation_lag_seconds=None,
        data_quality_flags=tuple(sorted(set(quality))),
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

    quote_notionals = [
        float(item.provider_swap_usd_value)
        for item in eligible
        if item.provider_swap_usd_value is not None
    ]
    quote_notional_min = min(quote_notionals) if quote_notionals else None
    quote_notional_max = max(quote_notionals) if quote_notionals else None

    quality: list[str] = []
    if not eligible:
        quality.append("no_causal_quotes_available")
    if not buys:
        quality.append("buy_quote_unavailable")
    if not sells:
        quality.append("sell_quote_unavailable")
    if eligible and not any(item.executable for item in eligible):
        quality.append("proxy_quotes_only")
    if (
        quote_notional_min is not None
        and quote_notional_max is not None
        and quote_notional_min > 0
        and quote_notional_max / quote_notional_min > 1.01
    ):
        quality.append("mixed_quote_notionals")
    if eligible and len(quote_notionals) < len(eligible):
        quality.append("partial_quote_notional_metadata")

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
        latest_buy_price_impact_pct_points=(latest_buy.provider_price_impact_pct_points if latest_buy else None),
        latest_sell_price_impact_pct_points=(latest_sell.provider_price_impact_pct_points if latest_sell else None),
        latest_buy_router=(latest_buy.provider_router if latest_buy else None),
        latest_sell_router=(latest_sell.provider_router if latest_sell else None),
        latest_buy_observation_age_seconds=(as_of - latest_buy.observed_at if latest_buy else None),
        latest_sell_observation_age_seconds=(as_of - latest_sell.observed_at if latest_sell else None),
        latest_buy_market_age_seconds=(as_of - latest_buy.market_time if latest_buy else None),
        latest_sell_market_age_seconds=(as_of - latest_sell.market_time if latest_sell else None),
        quote_notional_min_usd=quote_notional_min,
        quote_notional_max_usd=quote_notional_max,
        data_quality_flags=tuple(quality),
    )


def build_opportunity_snapshot_core_v1(
    *,
    token_mint: str,
    as_of: int,
    chain_as_of: int | None = None,
    flow_observations: list[FlowTradeObservation] | tuple[FlowTradeObservation, ...] = (),
    quotes: list[CausalQuoteObservation] | tuple[CausalQuoteObservation, ...] = (),
    flow_windows_seconds: tuple[int, ...] = DEFAULT_FLOW_WINDOWS_SECONDS,
) -> OpportunitySnapshotCoreV1:
    """Build a score-free causal T0 feature snapshot for research.

    ``as_of`` is the local evidence cutoff. An explicit ``chain_as_of`` is required
    when locally visible Solana flow exists and anchors all chain-time windows.
    Cross-domain observation lag is intentionally unavailable until a calibrated
    clock method exists.
    """

    if not token_mint.strip():
        raise ValueError("token_mint cannot be empty")
    if not isinstance(as_of, int) or isinstance(as_of, bool) or as_of < 0:
        raise ValueError("as_of must be a non-negative integer")
    if chain_as_of is not None and (
        not isinstance(chain_as_of, int) or isinstance(chain_as_of, bool) or chain_as_of < 0
    ):
        raise ValueError("chain_as_of must be a non-negative integer when present")
    if not flow_windows_seconds or any(
        not isinstance(item, int) or isinstance(item, bool) or item <= 0
        for item in flow_windows_seconds
    ):
        raise ValueError("flow windows must be positive integers")
    if len(set(flow_windows_seconds)) != len(flow_windows_seconds):
        raise ValueError("flow windows must be unique")

    normalized_flow: list[FlowTradeObservation] = []
    for item in flow_observations:
        _validate_flow_observation(item)
        if item.token_mint == token_mint:
            normalized_flow.append(item)

    locally_visible_flow = [item for item in normalized_flow if item.observed_at <= as_of]
    if locally_visible_flow and chain_as_of is None:
        raise ValueError("chain_as_of is required when locally visible flow exists")

    windows = tuple(
        _build_flow_window(
            normalized_flow,
            as_of=as_of,
            chain_as_of=chain_as_of if chain_as_of is not None else 0,
            window_seconds=window_seconds,
        )
        for window_seconds in sorted(flow_windows_seconds)
    )
    execution = build_execution_surface_features(quotes, token_mint=token_mint, as_of=as_of)

    quality: list[str] = []
    if not any(item.event_count for item in windows):
        quality.append("no_flow_context")
    if locally_visible_flow:
        quality.append("cross_clock_latency_not_calibrated")
    if execution.quote_count == 0:
        quality.append("no_execution_context")

    return OpportunitySnapshotCoreV1(
        token_mint=token_mint,
        as_of=as_of,
        chain_as_of=chain_as_of,
        method_version=OPPORTUNITY_SNAPSHOT_CORE_VERSION,
        flow_windows=windows,
        execution=execution,
        data_quality_flags=tuple(sorted(set(quality))),
    )
