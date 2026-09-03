"""Conservative causal economic replay for observed wallet actions.

The replay never manufactures an exit. Newer forward runs persist exact source-wallet
token balances, so repeated BUYs can be matched to observed source reductions without
the old ``one SELL == one BUY lot`` shortcut. Legacy actions without quantity metadata
retain the historical FIFO event-lot behavior for auditability.
"""
from dataclasses import dataclass, field
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


@dataclass
class _OpenLot:
    action: object
    entry_quote: CausalQuoteObservation
    remaining_fraction: float = 1.0
    realized_exit_value: float = 0.0
    last_exit_chain_time: int | None = None
    last_exit_observed_at: int | None = None
    missing_exit_quote: bool = False
    trackable: bool = True
    censored_reason: str | None = None
    flags: set[str] = field(default_factory=set)


@dataclass
class _QuantityState:
    initialized: bool = False
    copy_raw: int = 0
    noncopy_raw: int = 0
    copy_unknown: bool = False
    noncopy_unknown: bool = False


_QUANTITY_FIELDS = (
    "token_delta_raw",
    "token_balance_before_raw",
    "token_balance_after_raw",
    "source_reduction_fraction",
)
_EPS = 1e-9


def _quote(action, quotes, config, delay_seconds):
    sel = select_first_causal_quote(
        quotes, token_mint=action.token_mint, side=action.side,
        ready_at=action.observed_at + delay_seconds,
        max_quote_age_seconds=config.max_quote_age_seconds,
        max_quote_wait_seconds=config.max_quote_wait_seconds,
        require_executable=config.require_executable_quote,
    )
    return sel.quote, sel.reason


def _raw_int(action: object, name: str) -> int | None:
    value = getattr(action, name, None)
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _float_value(action: object, name: str) -> float | None:
    value = getattr(action, name, None)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quantity_capable(action: object) -> bool:
    return any(getattr(action, name, None) is not None for name in _QUANTITY_FIELDS)


def _event_quotes(action, quotes, quotes_by_event):
    if quotes_by_event is None:
        return tuple(quotes)
    return quotes_by_event.get(getattr(action, "observation_key", ""), tuple())


def _trade_from_closed_lot(lot: _OpenLot, config: EconomicReplayConfig) -> EconomicTrade:
    entry = lot.action
    eq = lot.entry_quote
    if lot.missing_exit_quote or lot.remaining_fraction > _EPS:
        raise ValueError("closed lot must have a complete quoted exit path")
    raw_exit = lot.realized_exit_value
    slip = config.slippage_bps / 10000
    buy = eq.price_usd * (1 + slip)
    sell = raw_exit * (1 - slip)
    gross = (raw_exit / eq.price_usd - 1) * 100
    net = (sell / buy - 1) * 100
    return EconomicTrade(
        entry.address,
        entry.token_mint,
        entry.chain_time,
        entry.observed_at,
        lot.last_exit_chain_time,
        lot.last_exit_observed_at,
        eq.price_usd,
        raw_exit,
        gross,
        net,
        config.notional_usd * net / 100,
        "CLOSED",
        "source_sell",
        tuple(sorted(lot.flags | {"quantity_aware"})),
    )


def _trade_from_censored_lot(
    lot: _OpenLot,
    *,
    reason: str | None,
    run_completed: bool,
) -> EconomicTrade:
    entry = lot.action
    explicit = reason or lot.censored_reason
    if explicit:
        status = "CENSORED"
        resolved_reason = explicit
    else:
        status = "RIGHT_CENSORED" if run_completed else "OPEN"
        resolved_reason = (
            "right_censored_no_source_sell" if run_completed else "open_no_source_sell"
        )
    flags = set(lot.flags)
    flags.add("censored")
    if explicit:
        flags.add("quantity_path_incomplete")
    return EconomicTrade(
        entry.address,
        entry.token_mint,
        entry.chain_time,
        entry.observed_at,
        lot.last_exit_chain_time,
        lot.last_exit_observed_at,
        lot.entry_quote.price_usd,
        None,
        None,
        None,
        None,
        status,
        resolved_reason,
        tuple(sorted(flags)),
    )


def _invalidate_trackable_lots(
    lots: list[_OpenLot],
    reason: str,
    *,
    flag: str,
) -> None:
    for lot in lots:
        if lot.trackable and lot.remaining_fraction > _EPS:
            lot.trackable = False
            lot.censored_reason = reason
            lot.flags.add(flag)


def _reconcile_before(
    state: _QuantityState,
    lots: list[_OpenLot],
    before_raw: int | None,
) -> None:
    if before_raw is None:
        return
    if not state.initialized:
        state.initialized = True
        state.noncopy_raw = max(0, before_raw)
        return
    if state.copy_unknown or state.noncopy_unknown:
        return
    tracked = state.copy_raw + state.noncopy_raw
    if before_raw > tracked:
        state.noncopy_raw += before_raw - tracked
    elif before_raw < tracked:
        _invalidate_trackable_lots(
            lots,
            "source_balance_reconciliation_mismatch",
            flag="source_balance_mismatch",
        )
        state.copy_raw = 0
        state.noncopy_raw = max(0, before_raw)


def _reset_after_ambiguous_sell(
    state: _QuantityState,
    after_raw: int | None,
) -> None:
    state.copy_raw = 0
    state.copy_unknown = False
    if after_raw is None:
        state.noncopy_raw = 0
        state.noncopy_unknown = True
    else:
        state.noncopy_raw = max(0, after_raw)
        state.noncopy_unknown = False
    state.initialized = True


def replay_source_wallet(
    actions: list[WalletActionObservation] | tuple[WalletActionObservation, ...],
    quotes: list[CausalQuoteObservation] | tuple[CausalQuoteObservation, ...],
    *,
    config: EconomicReplayConfig = EconomicReplayConfig(), delay_seconds: int = 0,
    quotes_by_event: dict[str, tuple[CausalQuoteObservation, ...]] | None = None,
    run_completed: bool = False,
) -> tuple[EconomicTrade, ...]:
    """Match causal BUY lots to observed source-wallet reductions.

    For quantity-aware runs, a complete source liquidation closes every trackable copy
    lot for the same wallet/token. A partial liquidation is mirrored proportionally
    only when the observed source inventory is entirely attributable to trackable copy
    BUYs. If pre-existing/non-copy inventory or quantity gaps make attribution
    ambiguous, the affected lots are censored instead of receiving invented exits.

    Legacy actions with no quantity metadata keep the historical one-SELL/one-FIFO-lot
    behavior so old runs remain reproducible.
    """
    if delay_seconds < 0 or delay_seconds not in config.delays:
        raise ValueError("delay_seconds must be one of config.delays")
    if config.notional_usd <= 0 or config.slippage_bps < 0:
        raise ValueError("invalid economic replay costs")

    ordered = sorted(actions, key=lambda a: (a.observed_at, a.chain_time))
    quantity_keys = {
        (a.address, a.token_mint)
        for a in ordered
        if _quantity_capable(a)
    }
    legacy_lots: dict[tuple[str, str], list[tuple[object, CausalQuoteObservation]]] = {}
    quantity_lots: dict[tuple[str, str], list[_OpenLot]] = {}
    quantity_states: dict[tuple[str, str], _QuantityState] = {}
    out: list[EconomicTrade] = []
    slip = config.slippage_bps / 10000

    for action in ordered:
        key = (action.address, action.token_mint)
        economic_eligible = bool(getattr(action, "economic_eligible", True))

        if key not in quantity_keys:
            if action.side == "buy":
                if not economic_eligible:
                    continue
                event_quotes = _event_quotes(action, quotes, quotes_by_event)
                quote, reason = _quote(action, event_quotes, config, delay_seconds)
                if quote is None:
                    out.append(EconomicTrade(
                        action.address, action.token_mint,
                        action.chain_time, action.observed_at,
                        None, None, None, None, None, None, None,
                        "OPEN", reason or "missing_entry_quote",
                        ("missing_entry_quote",),
                    ))
                else:
                    legacy_lots.setdefault(key, []).append((action, quote))
                continue

            if not legacy_lots.get(key):
                continue
            entry, eq = legacy_lots[key].pop(0)
            event_quotes = _event_quotes(action, quotes, quotes_by_event)
            quote, reason = _quote(action, event_quotes, config, delay_seconds)
            if quote is None:
                out.append(EconomicTrade(
                    action.address, action.token_mint,
                    entry.chain_time, entry.observed_at,
                    action.chain_time, action.observed_at,
                    eq.price_usd, None, None, None, None,
                    "CENSORED", reason or "missing_exit_quote",
                    ("exit_unobserved",),
                ))
                continue
            buy = eq.price_usd * (1 + slip)
            sell = quote.price_usd * (1 - slip)
            gross = (quote.price_usd / eq.price_usd - 1) * 100
            net = (sell / buy - 1) * 100
            out.append(EconomicTrade(
                action.address, action.token_mint,
                entry.chain_time, entry.observed_at,
                action.chain_time, action.observed_at,
                eq.price_usd, quote.price_usd,
                gross, net, config.notional_usd * net / 100,
                "CLOSED", "source_sell", (),
            ))
            continue

        lots = quantity_lots.setdefault(key, [])
        state = quantity_states.setdefault(key, _QuantityState())
        before_raw = _raw_int(action, "token_balance_before_raw")
        after_raw = _raw_int(action, "token_balance_after_raw")
        delta_raw = _raw_int(action, "token_delta_raw")
        _reconcile_before(state, lots, before_raw)

        if action.side == "buy":
            valid_delta = delta_raw is not None and delta_raw > 0
            if not economic_eligible:
                if valid_delta:
                    state.noncopy_raw += delta_raw
                else:
                    state.noncopy_unknown = True
                state.initialized = True
                continue

            event_quotes = _event_quotes(action, quotes, quotes_by_event)
            quote, reason = _quote(action, event_quotes, config, delay_seconds)
            if quote is None:
                out.append(EconomicTrade(
                    action.address, action.token_mint,
                    action.chain_time, action.observed_at,
                    None, None, None, None, None, None, None,
                    "OPEN", reason or "missing_entry_quote",
                    ("missing_entry_quote", "quantity_aware"),
                ))
                if valid_delta:
                    state.noncopy_raw += delta_raw
                else:
                    state.noncopy_unknown = True
                state.initialized = True
                continue

            lot = _OpenLot(action=action, entry_quote=quote)
            if valid_delta:
                state.copy_raw += delta_raw
            else:
                state.copy_unknown = True
                lot.flags.add("source_buy_quantity_unknown")
            lots.append(lot)
            state.initialized = True
            continue

        valid_delta = delta_raw is not None and delta_raw < 0
        fraction = _float_value(action, "source_reduction_fraction")
        full_reduction = (
            valid_delta
            and (
                after_raw == 0
                or (fraction is not None and fraction >= 1.0 - _EPS)
            )
        )
        current_lots = [lot for lot in lots if lot.remaining_fraction > _EPS]

        if not valid_delta or before_raw is None or after_raw is None:
            _invalidate_trackable_lots(
                current_lots,
                "source_quantity_unknown_on_sell",
                flag="source_quantity_unknown",
            )
            _reset_after_ambiguous_sell(state, after_raw)
            continue

        if full_reduction:
            event_quotes = _event_quotes(action, quotes, quotes_by_event)
            quote, reason = _quote(action, event_quotes, config, delay_seconds)
            for lot in current_lots:
                if not lot.trackable:
                    out.append(_trade_from_censored_lot(
                        lot,
                        reason=lot.censored_reason or "ambiguous_source_allocation",
                        run_completed=run_completed,
                    ))
                    continue
                piece = lot.remaining_fraction
                lot.last_exit_chain_time = action.chain_time
                lot.last_exit_observed_at = action.observed_at
                lot.flags.add("source_complete_reduction")
                if quote is None:
                    lot.missing_exit_quote = True
                    out.append(_trade_from_censored_lot(
                        lot,
                        reason=reason or "missing_exit_quote",
                        run_completed=run_completed,
                    ))
                else:
                    lot.realized_exit_value += piece * quote.price_usd
                    lot.remaining_fraction = 0.0
                    out.append(_trade_from_closed_lot(lot, config))
            quantity_lots[key] = []
            state.copy_raw = 0
            state.noncopy_raw = 0
            state.copy_unknown = False
            state.noncopy_unknown = False
            state.initialized = True
            continue

        sold_raw = abs(delta_raw)
        if before_raw <= 0 or sold_raw <= 0 or sold_raw > before_raw:
            _invalidate_trackable_lots(
                current_lots,
                "source_quantity_inconsistent_on_sell",
                flag="source_quantity_inconsistent",
            )
            _reset_after_ambiguous_sell(state, after_raw)
            continue

        clean_partial = (
            not state.copy_unknown
            and not state.noncopy_unknown
            and state.noncopy_raw == 0
            and state.copy_raw == before_raw
        )
        if not clean_partial:
            _invalidate_trackable_lots(
                current_lots,
                "ambiguous_partial_source_sell",
                flag="preexisting_or_noncopy_inventory",
            )
            _reset_after_ambiguous_sell(state, after_raw)
            continue

        reduction = sold_raw / before_raw
        event_quotes = _event_quotes(action, quotes, quotes_by_event)
        quote, reason = _quote(action, event_quotes, config, delay_seconds)
        for lot in current_lots:
            if not lot.trackable:
                continue
            piece = lot.remaining_fraction * reduction
            lot.remaining_fraction = max(0.0, lot.remaining_fraction - piece)
            lot.last_exit_chain_time = action.chain_time
            lot.last_exit_observed_at = action.observed_at
            lot.flags.add("source_proportional_reduction")
            if quote is None:
                lot.missing_exit_quote = True
                lot.flags.add("missing_partial_exit_quote")
            else:
                lot.realized_exit_value += piece * quote.price_usd
        state.copy_raw = after_raw
        state.noncopy_raw = 0
        state.initialized = True

    for (wallet, token), lots in legacy_lots.items():
        for entry, eq in lots:
            status = "RIGHT_CENSORED" if run_completed else "OPEN"
            reason = (
                "right_censored_no_source_sell" if run_completed else "open_no_source_sell"
            )
            out.append(EconomicTrade(
                wallet, token, entry.chain_time, entry.observed_at,
                None, None, eq.price_usd, None, None, None, None,
                status, reason, ("censored",),
            ))

    for lots in quantity_lots.values():
        for lot in lots:
            if lot.remaining_fraction <= _EPS:
                continue
            reason = lot.censored_reason
            if lot.missing_exit_quote:
                reason = reason or "missing_partial_exit_quote"
            out.append(_trade_from_censored_lot(
                lot,
                reason=reason,
                run_completed=run_completed,
            ))

    return tuple(out)


def summarize_economic_replay(trades, *, buy_count: int, actions=()):
    rows = list(trades)
    closed = [r for r in rows if r.status == "CLOSED"]
    returns = [r.net_return_pct for r in closed if r.net_return_pct is not None]
    gains = sum(r.pnl_usd for r in closed if r.pnl_usd and r.pnl_usd > 0)
    losses = -sum(r.pnl_usd for r in closed if r.pnl_usd and r.pnl_usd < 0)
    keys = {(r.wallet_address, r.token_mint) for r in rows}
    return EconomicReplaySummary(
        buy_count=buy_count,
        closed_count=len(closed),
        open_count=sum(r.status == "OPEN" for r in rows),
        censored_count=sum(r.status in {"CENSORED", "RIGHT_CENSORED"} for r in rows),
        missing_quote_count=sum("missing" in r.reason for r in rows),
        repeated_buy_count=max(0, buy_count - len(keys)),
        wallet_count=len({r.wallet_address for r in rows}),
        token_count=len({r.token_mint for r in rows}),
        cluster_count=len(keys),
        mean_net_return_pct=(sum(returns) / len(returns) if returns else None),
        median_net_return_pct=(median(returns) if returns else None),
        win_rate_pct=(100 * sum(r > 0 for r in returns) / len(returns) if returns else None),
        profit_factor=(gains / losses if losses else None),
    )
