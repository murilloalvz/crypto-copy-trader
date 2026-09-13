from __future__ import annotations

from dataclasses import dataclass
import math

from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation


LAUNCH_BURST_VERSION = "launch_burst_v0_causal_lifecycle_snapshot"
SUPPORTED_LAUNCH_VENUES = frozenset({"pump_bonding_curve", "pump_swap"})


@dataclass(frozen=True)
class LaunchBurstConfig:
    observation_window_seconds: int = 30


@dataclass(frozen=True)
class LaunchBurstSnapshot:
    token_mint: str
    venue: str
    stratum: str
    method_version: str
    chain_t0: int
    observed_t0: int
    decision_as_of: int
    chain_window_end: int
    event_count: int
    buy_count: int
    sell_count: int
    unique_wallet_count: int
    unique_transaction_count: int
    wallet_identity_coverage_pct: float | None
    transaction_identity_coverage_pct: float | None
    notional_coverage_pct: float | None
    price_coverage_pct: float | None
    known_buy_notional_usd: float
    known_sell_notional_usd: float
    known_notional_usd: float
    known_notional_buy_share_pct: float | None
    count_buy_share_pct: float | None
    first_trade_chain_delay_seconds: int | None
    first_trade_observed_delay_seconds: int | None
    first_price_usd: float | None
    last_price_usd: float | None
    window_return_pct: float | None
    data_quality_flags: tuple[str, ...]


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _coverage(known: int, total: int) -> float | None:
    if total <= 0:
        return None
    return 100.0 * known / total


def _validate_config(config: LaunchBurstConfig) -> None:
    if not isinstance(config.observation_window_seconds, int) or isinstance(
        config.observation_window_seconds, bool
    ):
        raise ValueError("observation_window_seconds must be an integer")
    if config.observation_window_seconds <= 0:
        raise ValueError("observation_window_seconds must be positive")


def _validate_lifecycle(lifecycle: MarketLifecycleObservation) -> tuple[str, str]:
    token = _required(lifecycle.token_mint, "lifecycle token_mint")
    venue = _required(lifecycle.venue or "", "lifecycle venue")
    if venue not in SUPPORTED_LAUNCH_VENUES:
        raise ValueError(f"unsupported launch venue: {venue}")
    if lifecycle.market_started_at < 0 or lifecycle.observed_at < 0:
        raise ValueError("lifecycle timestamps must be non-negative")
    return token, venue


def _validate_trade(trade: MarketTradeObservation) -> None:
    _required(trade.token_mint, "trade token_mint")
    if trade.side not in {"buy", "sell"}:
        raise ValueError("trade side must be buy or sell")
    if trade.chain_time < 0 or trade.observed_at < 0:
        raise ValueError("trade timestamps must be non-negative")
    if trade.notional_usd is not None and (
        trade.notional_usd < 0 or not math.isfinite(trade.notional_usd)
    ):
        raise ValueError("trade notional_usd must be non-negative and finite")
    if trade.price_usd is not None and (
        trade.price_usd <= 0 or not math.isfinite(trade.price_usd)
    ):
        raise ValueError("trade price_usd must be positive and finite")


def launch_stratum_for_venue(venue: str) -> str:
    normalized = _required(venue, "venue")
    if normalized == "pump_bonding_curve":
        return "pump_launch"
    if normalized == "pump_swap":
        return "pumpswap_liquidity_launch"
    raise ValueError(f"unsupported launch venue: {normalized}")


def build_launch_burst_snapshot(
    trades: list[MarketTradeObservation] | tuple[MarketTradeObservation, ...],
    *,
    lifecycle: MarketLifecycleObservation,
    decision_as_of: int,
    config: LaunchBurstConfig = LaunchBurstConfig(),
) -> LaunchBurstSnapshot:
    """Build one causal post-launch feature snapshot.

    ``market_started_at`` and trade ``chain_time`` form the chain clock. Lifecycle/trade
    ``observed_at`` and ``decision_as_of`` form the local evidence-availability clock.
    The two domains are never subtracted from one another.

    A trade is eligible only when it belongs to the same token, was available locally by
    ``decision_as_of``, and its chain timestamp is inside the fixed post-launch window.
    The function produces research features only; it never emits a BUY/SELL decision.
    """

    _validate_config(config)
    token, venue = _validate_lifecycle(lifecycle)
    if not isinstance(decision_as_of, int) or isinstance(decision_as_of, bool):
        raise ValueError("decision_as_of must be an integer")
    if decision_as_of < lifecycle.observed_at:
        raise ValueError("decision_as_of cannot precede lifecycle observed_t0")

    for trade in trades:
        _validate_trade(trade)

    chain_t0 = int(lifecycle.market_started_at)
    observed_t0 = int(lifecycle.observed_at)
    chain_window_end = chain_t0 + config.observation_window_seconds

    eligible = [
        trade
        for trade in trades
        if trade.token_mint == token
        and trade.observed_at <= decision_as_of
        and chain_t0 <= trade.chain_time <= chain_window_end
    ]
    eligible.sort(
        key=lambda trade: (
            trade.chain_time,
            trade.observed_at,
            trade.transaction_key or "",
            trade.wallet_address or "",
            trade.side,
        )
    )

    buys = [trade for trade in eligible if trade.side == "buy"]
    sells = [trade for trade in eligible if trade.side == "sell"]
    wallet_rows = [trade for trade in eligible if trade.wallet_address is not None]
    transaction_rows = [trade for trade in eligible if trade.transaction_key is not None]
    notional_rows = [trade for trade in eligible if trade.notional_usd is not None]
    price_rows = [trade for trade in eligible if trade.price_usd is not None]

    known_buy_notional = sum(
        float(trade.notional_usd) for trade in buys if trade.notional_usd is not None
    )
    known_sell_notional = sum(
        float(trade.notional_usd) for trade in sells if trade.notional_usd is not None
    )
    known_notional = known_buy_notional + known_sell_notional
    known_notional_buy_share = (
        100.0 * known_buy_notional / known_notional if known_notional > 0 else None
    )
    count_buy_share = 100.0 * len(buys) / len(eligible) if eligible else None

    prices_complete = bool(eligible) and len(price_rows) == len(eligible)
    first_price = float(eligible[0].price_usd) if prices_complete else None
    last_price = float(eligible[-1].price_usd) if prices_complete else None
    window_return = None
    if first_price is not None and last_price is not None and len(eligible) >= 2:
        window_return = 100.0 * (last_price / first_price - 1.0)

    flags: list[str] = []
    if not eligible:
        flags.append("no_events_in_launch_window")
    if eligible and len(wallet_rows) < len(eligible):
        flags.append("partial_wallet_identity_coverage")
    if eligible and len(transaction_rows) < len(eligible):
        flags.append("partial_transaction_identity_coverage")
    if eligible and len(notional_rows) < len(eligible):
        flags.append("partial_notional_coverage")
    if eligible and len(price_rows) < len(eligible):
        flags.append("partial_price_coverage")
    if any(trade.observed_at < observed_t0 for trade in eligible):
        flags.append("trade_observed_before_lifecycle_anchor")

    first_chain_delay = eligible[0].chain_time - chain_t0 if eligible else None
    first_observed_delay = (
        min(trade.observed_at for trade in eligible) - observed_t0 if eligible else None
    )

    return LaunchBurstSnapshot(
        token_mint=token,
        venue=venue,
        stratum=launch_stratum_for_venue(venue),
        method_version=LAUNCH_BURST_VERSION,
        chain_t0=chain_t0,
        observed_t0=observed_t0,
        decision_as_of=decision_as_of,
        chain_window_end=chain_window_end,
        event_count=len(eligible),
        buy_count=len(buys),
        sell_count=len(sells),
        unique_wallet_count=len({str(trade.wallet_address) for trade in wallet_rows}),
        unique_transaction_count=len(
            {str(trade.transaction_key) for trade in transaction_rows}
        ),
        wallet_identity_coverage_pct=_coverage(len(wallet_rows), len(eligible)),
        transaction_identity_coverage_pct=_coverage(
            len(transaction_rows), len(eligible)
        ),
        notional_coverage_pct=_coverage(len(notional_rows), len(eligible)),
        price_coverage_pct=_coverage(len(price_rows), len(eligible)),
        known_buy_notional_usd=known_buy_notional,
        known_sell_notional_usd=known_sell_notional,
        known_notional_usd=known_notional,
        known_notional_buy_share_pct=known_notional_buy_share,
        count_buy_share_pct=count_buy_share,
        first_trade_chain_delay_seconds=first_chain_delay,
        first_trade_observed_delay_seconds=first_observed_delay,
        first_price_usd=first_price,
        last_price_usd=last_price,
        window_return_pct=window_return,
        data_quality_flags=tuple(flags),
    )
