from dataclasses import dataclass
from statistics import median

from src.causal_quotes import CausalQuoteObservation, select_first_causal_quote
from src.opportunity_intelligence import WalletActionObservation


@dataclass(frozen=True)
class WalletCausalReplayConfig:
    decision_delay_seconds: int = 0
    slippage_bps: int = 100
    max_quote_age_seconds: int = 15
    max_quote_wait_seconds: int = 30
    require_executable_quote: bool = True


@dataclass(frozen=True)
class WalletActionReplay:
    address: str
    token_mint: str
    side: str
    chain_time: int
    source_observed_at: int
    decision_ready_at: int
    source_lag_seconds: int
    status: str
    reason: str | None
    quote_market_time: int | None
    quote_observed_at: int | None
    quote_wait_seconds: int | None
    quote_age_seconds: int | None
    total_chain_to_quote_seconds: int | None
    market_price_usd: float | None
    simulated_execution_price_usd: float | None
    liquidity_usd: float | None
    quote_source: str | None
    quote_resolution_seconds: int | None
    quote_executable: bool | None


@dataclass(frozen=True)
class WalletCausalReplaySummary:
    action_count: int
    filled_count: int
    missing_count: int
    fill_coverage_pct: float
    wallet_count: int
    token_count: int
    median_source_lag_seconds: float | None
    median_quote_wait_seconds: float | None
    p95_total_chain_to_quote_seconds: float | None
    executable_fill_count: int
    proxy_fill_count: int


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _validate_config(config: WalletCausalReplayConfig) -> None:
    if config.decision_delay_seconds < 0:
        raise ValueError("decision_delay_seconds must be non-negative")
    if not 0 <= config.slippage_bps <= 10_000:
        raise ValueError("slippage_bps must be between 0 and 10000")
    if config.max_quote_age_seconds < 0:
        raise ValueError("max_quote_age_seconds must be non-negative")
    if config.max_quote_wait_seconds < 0:
        raise ValueError("max_quote_wait_seconds must be non-negative")


def _validate_action(action: WalletActionObservation) -> None:
    if not action.address.strip():
        raise ValueError("wallet address cannot be empty")
    if not action.token_mint.strip():
        raise ValueError("wallet token_mint cannot be empty")
    if action.side not in {"buy", "sell"}:
        raise ValueError("wallet side must be buy or sell")
    if action.chain_time < 0 or action.observed_at < 0:
        raise ValueError("wallet timestamps must be non-negative")
    if action.observed_at < action.chain_time:
        raise ValueError("wallet observed_at cannot be earlier than chain_time")


def replay_wallet_action(
    action: WalletActionObservation,
    quotes: list[CausalQuoteObservation] | tuple[CausalQuoteObservation, ...],
    *,
    config: WalletCausalReplayConfig = WalletCausalReplayConfig(),
) -> WalletActionReplay:
    _validate_config(config)
    _validate_action(action)

    source_lag = action.observed_at - action.chain_time
    decision_ready_at = action.observed_at + config.decision_delay_seconds
    selection = select_first_causal_quote(
        quotes,
        token_mint=action.token_mint,
        ready_at=decision_ready_at,
        max_quote_age_seconds=config.max_quote_age_seconds,
        max_quote_wait_seconds=config.max_quote_wait_seconds,
        require_executable=config.require_executable_quote,
    )

    quote = selection.quote
    if quote is None:
        return WalletActionReplay(
            address=action.address,
            token_mint=action.token_mint,
            side=action.side,
            chain_time=action.chain_time,
            source_observed_at=action.observed_at,
            decision_ready_at=decision_ready_at,
            source_lag_seconds=source_lag,
            status="missing_quote",
            reason=selection.reason,
            quote_market_time=None,
            quote_observed_at=None,
            quote_wait_seconds=None,
            quote_age_seconds=None,
            total_chain_to_quote_seconds=None,
            market_price_usd=None,
            simulated_execution_price_usd=None,
            liquidity_usd=None,
            quote_source=None,
            quote_resolution_seconds=None,
            quote_executable=None,
        )

    slippage_fraction = config.slippage_bps / 10_000
    execution_price = (
        quote.price_usd * (1 + slippage_fraction)
        if action.side == "buy"
        else quote.price_usd * (1 - slippage_fraction)
    )
    return WalletActionReplay(
        address=action.address,
        token_mint=action.token_mint,
        side=action.side,
        chain_time=action.chain_time,
        source_observed_at=action.observed_at,
        decision_ready_at=decision_ready_at,
        source_lag_seconds=source_lag,
        status="filled",
        reason=None,
        quote_market_time=quote.market_time,
        quote_observed_at=quote.observed_at,
        quote_wait_seconds=quote.observed_at - decision_ready_at,
        quote_age_seconds=quote.observed_at - quote.market_time,
        total_chain_to_quote_seconds=quote.observed_at - action.chain_time,
        market_price_usd=quote.price_usd,
        simulated_execution_price_usd=execution_price,
        liquidity_usd=quote.liquidity_usd,
        quote_source=quote.source,
        quote_resolution_seconds=quote.resolution_seconds,
        quote_executable=quote.executable,
    )


def replay_wallet_actions(
    actions: list[WalletActionObservation] | tuple[WalletActionObservation, ...],
    quotes: list[CausalQuoteObservation] | tuple[CausalQuoteObservation, ...],
    *,
    config: WalletCausalReplayConfig = WalletCausalReplayConfig(),
) -> list[WalletActionReplay]:
    _validate_config(config)
    return [replay_wallet_action(action, quotes, config=config) for action in actions]


def summarize_wallet_causal_replay(
    results: list[WalletActionReplay] | tuple[WalletActionReplay, ...],
) -> WalletCausalReplaySummary:
    rows = list(results)
    filled = [row for row in rows if row.status == "filled"]
    source_lags = [float(row.source_lag_seconds) for row in rows]
    quote_waits = [
        float(row.quote_wait_seconds)
        for row in filled
        if row.quote_wait_seconds is not None
    ]
    total_lags = [
        float(row.total_chain_to_quote_seconds)
        for row in filled
        if row.total_chain_to_quote_seconds is not None
    ]
    return WalletCausalReplaySummary(
        action_count=len(rows),
        filled_count=len(filled),
        missing_count=len(rows) - len(filled),
        fill_coverage_pct=(100.0 * len(filled) / len(rows) if rows else 0.0),
        wallet_count=len({row.address for row in rows}),
        token_count=len({row.token_mint for row in rows}),
        median_source_lag_seconds=median(source_lags) if source_lags else None,
        median_quote_wait_seconds=median(quote_waits) if quote_waits else None,
        p95_total_chain_to_quote_seconds=_percentile(total_lags, 0.95),
        executable_fill_count=sum(row.quote_executable is True for row in filled),
        proxy_fill_count=sum(row.quote_executable is False for row in filled),
    )
