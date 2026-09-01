"""Conservative causal economic replay for observed wallet actions.

This module deliberately uses no candles and never manufactures an exit.  Because the
forward action schema has no token quantities, matching is event-lot based (one lot per
BUY); results are returns, not a claim about the wallet's realized dollar PnL.
"""
from dataclasses import dataclass
from statistics import median

from src.causal_quotes import CausalQuoteObservation, select_first_causal_quote
from src.opportunity_intelligence import WalletActionObservation


@dataclass(frozen=True)
class EconomicReplayConfig:
    delays: tuple[int, ...] = (0, 15, 30, 60, 120)
    slippage_bps: int = 100
    notional_usd: float = 25.0
    max_quote_age_seconds: int = 15
    max_quote_wait_seconds: int = 30
    require_executable_quote: bool = True


@dataclass(frozen=True)
class EconomicTrade:
    wallet_address: str
    token_mint: str
    entry_chain_time: int
    entry_observed_at: int
    exit_chain_time: int | None
    exit_observed_at: int | None
    entry_price_usd: float | None
    exit_price_usd: float | None
    gross_return_pct: float | None
    net_return_pct: float | None
    pnl_usd: float | None
    status: str
    reason: str
    flags: tuple[str, ...]


@dataclass(frozen=True)
class EconomicReplaySummary:
    buy_count: int
    closed_count: int
    open_count: int
    censored_count: int
    missing_quote_count: int
    repeated_buy_count: int
    wallet_count: int
    token_count: int
    cluster_count: int
    mean_net_return_pct: float | None
    median_net_return_pct: float | None
    win_rate_pct: float | None
    profit_factor: float | None


def _quote(action, quotes, config, delay_seconds):
    sel = select_first_causal_quote(
        quotes, token_mint=action.token_mint, side=action.side,
        ready_at=action.observed_at + delay_seconds,
        max_quote_age_seconds=config.max_quote_age_seconds,
        max_quote_wait_seconds=config.max_quote_wait_seconds,
        require_executable=config.require_executable_quote,
    )
    return sel.quote, sel.reason


def replay_source_wallet(
    actions: list[WalletActionObservation] | tuple[WalletActionObservation, ...],
    quotes: list[CausalQuoteObservation] | tuple[CausalQuoteObservation, ...],
    *, config: EconomicReplayConfig = EconomicReplayConfig(), delay_seconds: int = 0,
) -> tuple[EconomicTrade, ...]:
    """Match causal BUY lots to later SELLs for the same wallet/token.

    A SELL before any forward BUY is explicitly ignored as pre-existing inventory.  A
    BUY without a later matched SELL is OPEN/CENSORED and has no return.
    """
    if delay_seconds < 0 or delay_seconds not in config.delays:
        raise ValueError("delay_seconds must be one of config.delays")
    if config.notional_usd <= 0 or config.slippage_bps < 0:
        raise ValueError("invalid economic replay costs")
    ordered = sorted(actions, key=lambda a: (a.observed_at, a.chain_time))
    open_lots: dict[tuple[str, str], list[tuple[WalletActionObservation, CausalQuoteObservation]]] = {}
    out: list[EconomicTrade] = []
    slip = config.slippage_bps / 10000
    for action in ordered:
        if action.side == "buy":
            quote, reason = _quote(action, quotes, config, delay_seconds)
            key = (action.address, action.token_mint)
            if quote is None:
                out.append(EconomicTrade(action.address, action.token_mint, action.chain_time, action.observed_at, None, None, None, None, None, None, None, "OPEN", reason or "missing_entry_quote", ("missing_entry_quote",)))
            else:
                open_lots.setdefault(key, []).append((action, quote))
        else:
            key = (action.address, action.token_mint)
            if not open_lots.get(key):
                continue
            entry, eq = open_lots[key].pop(0)
            quote, reason = _quote(action, quotes, config, delay_seconds)
            if quote is None:
                out.append(EconomicTrade(action.address, action.token_mint, entry.chain_time, entry.observed_at, action.chain_time, action.observed_at, eq.price_usd, None, None, None, None, "CENSORED", reason or "missing_exit_quote", ("exit_unobserved",)))
                continue
            buy = eq.price_usd * (1 + slip); sell = quote.price_usd * (1 - slip)
            gross = (quote.price_usd / eq.price_usd - 1) * 100
            net = (sell / buy - 1) * 100
            out.append(EconomicTrade(action.address, action.token_mint, entry.chain_time, entry.observed_at, action.chain_time, action.observed_at, eq.price_usd, quote.price_usd, gross, net, config.notional_usd * net / 100, "CLOSED", "source_sell", ()))
    for (wallet, token), lots in open_lots.items():
        for entry, eq in lots:
            out.append(EconomicTrade(wallet, token, entry.chain_time, entry.observed_at, None, None, eq.price_usd, None, None, None, None, "OPEN", "right_censored_no_source_sell", ("censored",)))
    return tuple(out)


def summarize_economic_replay(trades, *, buy_count: int, actions=()):
    rows = list(trades); closed = [r for r in rows if r.status == "CLOSED"]
    returns = [r.net_return_pct for r in closed if r.net_return_pct is not None]
    gains = sum(r.pnl_usd for r in closed if r.pnl_usd and r.pnl_usd > 0)
    losses = -sum(r.pnl_usd for r in closed if r.pnl_usd and r.pnl_usd < 0)
    keys = {(r.wallet_address, r.token_mint) for r in rows}
    return EconomicReplaySummary(
        buy_count=buy_count, closed_count=len(closed), open_count=sum(r.status == "OPEN" for r in rows),
        censored_count=sum(r.status == "CENSORED" for r in rows), missing_quote_count=sum("missing" in r.reason for r in rows),
        repeated_buy_count=max(0, buy_count-len(keys)), wallet_count=len({r.wallet_address for r in rows}),
        token_count=len({r.token_mint for r in rows}), cluster_count=len(keys),
        mean_net_return_pct=(sum(returns)/len(returns) if returns else None), median_net_return_pct=(median(returns) if returns else None),
        win_rate_pct=(100*sum(r>0 for r in returns)/len(returns) if returns else None), profit_factor=(gains/losses if losses else None),
    )
