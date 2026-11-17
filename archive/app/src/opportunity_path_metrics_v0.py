"""SIG-FAST V0 price-path instrument (F2 of the 2026-10-08 work order).

Measures a signal by the PRICE PATH after it, not by a return at a fixed horizon.

MFE ("how far it ran to the top") is reported as a separate, explicitly-labeled
field everywhere in this module and is a hindsight-only theoretical ceiling. It
is NEVER an edge metric and must never be averaged, summed, or otherwise mixed
into a return/P&L number by any caller. Edge is measured elsewhere (F3: signal
vs. a paired random baseline; net EV under a pre-fixed exit rule, computed
here by `simulate_exit`).

Every entry/exit is causal: it is resolved from the first trade at or after
`signal_time + latency_seconds` (entry) or `trigger_time + exit_latency_seconds`
(exit). No function here ever looks at a trade strictly after the one it
selects to make that selection -- this is covered by a dedicated causality
test in tests/test_opportunity_path_metrics_v0.py.

Price is derived, not persisted (see docs/sig-fast-price-path-persistence-v0-design-2026-10-08.md):
either from a trade's own executed amounts (`executed_trade_price_sol`) or from
a trade's post-trade pool reserves (`mid_price_sol`), using SPL mint decimals as
explicit, named protocol constants (pump.fun base tokens: 6; SOL/WSOL: 9) -- never
silently assumed inside a formula without being a visible parameter.

Missingness is explicit: a trade missing the fields needed to derive a price
contributes nothing and is skipped, never treated as zero or as a repeat of the
last known price without a flag. A token falling to near-zero is real P&L, not
excluded; it shows up as a strongly negative return, not a gap in the data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

VERSION = "opportunity_path_metrics_v0"

# Grids named in the work order. These are declared here for F5's discovery
# sweep to iterate over; this module itself takes one point of the grid per
# call rather than orchestrating the sweep (that is F5/F7's job).
ENTRY_LATENCY_GRID_SECONDS: tuple[int, ...] = (5, 15, 30, 60, 120)
EXIT_LATENCY_GRID_SECONDS: tuple[int, ...] = (5, 15, 30, 60, 120)
WINDOW_GRID_SECONDS: tuple[int, ...] = (60, 300, 900, 3600)
TARGET_GRID_PCT: tuple[float, ...] = (20.0, 50.0, 100.0, 200.0)
STOP_GRID_PCT: tuple[float, ...] = (-20.0, -30.0, -50.0)

# SPL mint decimals are a protocol-level constant, not a per-token guess: every
# pump.fun-launched base token is minted with 6 decimals; SOL/WSOL always has 9.
DEFAULT_BASE_DECIMALS = 6
DEFAULT_QUOTE_DECIMALS = 9

# A trade-to-trade gap wider than this is flagged, never silently treated as a
# live/fresh price.
DEFAULT_GAP_FLAG_SECONDS = 60

# A price jump across a venue-migration boundary wider than this (in percent)
# is flagged as a possible discontinuity rather than trusted at face value.
DEFAULT_MIGRATION_DISCONTINUITY_FLAG_PCT = 50.0


@dataclass(frozen=True)
class PathTrade:
    """One causal trade observation, as persisted by F1b."""

    chain_time: int
    venue: str
    base_amount_raw: int | None = None
    quote_amount_raw: int | None = None
    base_reserves_raw: int | None = None
    quote_reserves_raw: int | None = None


@dataclass(frozen=True)
class CostModel:
    """All percentages are per leg (one buy or one sell), not round-trip.

    venue_fee_pct and terminal_fee_pct have no defaults on purpose: F4 has not
    been researched yet at the time this module is written, and a silent
    default here would be exactly the "nada inventado" violation the work
    order warns against. Callers must pass explicit values (0.0 is a valid
    explicit value for a what-if scenario; it is just not an assumed default).
    """

    venue_fee_pct: float
    terminal_fee_pct: float
    network_fee_sol: float = 0.0003
    ata_fee_sol: float = 0.0

    def __post_init__(self) -> None:
        if self.venue_fee_pct < 0 or self.terminal_fee_pct < 0:
            raise ValueError("fee percentages cannot be negative")
        if self.network_fee_sol < 0 or self.ata_fee_sol < 0:
            raise ValueError("flat fees cannot be negative")

    @property
    def total_fee_pct(self) -> float:
        return self.venue_fee_pct + self.terminal_fee_pct


def mid_price_sol(
    trade: PathTrade,
    *,
    base_decimals: int = DEFAULT_BASE_DECIMALS,
    quote_decimals: int = DEFAULT_QUOTE_DECIMALS,
) -> float | None:
    """Pool mid price (quote/base) implied by this trade's post-trade reserves."""

    if trade.base_reserves_raw is None or trade.quote_reserves_raw is None:
        return None
    if trade.base_reserves_raw <= 0:
        return None
    return (trade.quote_reserves_raw / 10**quote_decimals) / (
        trade.base_reserves_raw / 10**base_decimals
    )


def executed_trade_price_sol(
    trade: PathTrade,
    *,
    base_decimals: int = DEFAULT_BASE_DECIMALS,
    quote_decimals: int = DEFAULT_QUOTE_DECIMALS,
) -> float | None:
    """The price this specific trade actually executed at (quote/base, both sides)."""

    if trade.base_amount_raw is None or trade.quote_amount_raw is None:
        return None
    if trade.base_amount_raw <= 0:
        return None
    return (trade.quote_amount_raw / 10**quote_decimals) / (
        trade.base_amount_raw / 10**base_decimals
    )


def _constant_product_buy_base_out_raw(
    *, base_reserves_raw: int, quote_reserves_raw: int, effective_quote_in_raw: float
) -> float:
    """x*y=k swap: how much base comes out for `effective_quote_in_raw` of quote in."""

    return base_reserves_raw * effective_quote_in_raw / (quote_reserves_raw + effective_quote_in_raw)


def _constant_product_sell_quote_out_raw(
    *, base_reserves_raw: int, quote_reserves_raw: int, base_in_raw: float
) -> float:
    return quote_reserves_raw * base_in_raw / (base_reserves_raw + base_in_raw)


def simulate_amm_buy_execution_price_sol(
    *,
    reserves_trade: PathTrade,
    size_sol: float,
    cost_model: CostModel,
    base_decimals: int = DEFAULT_BASE_DECIMALS,
    quote_decimals: int = DEFAULT_QUOTE_DECIMALS,
) -> float | None:
    """Average execution price (SOL per token) for a hypothetical buy of `size_sol`,
    simulated against `reserves_trade`'s post-trade reserves as the pool-state proxy
    (we do not have a separate pre-trade snapshot; this is the nearest available
    state to our hypothetical entry and is treated as an explicit approximation,
    not a precise order-book read). Includes venue + terminal fee and constant-
    product slippage; does not include the flat network/ATA fee (apply separately).
    """

    if (
        reserves_trade.base_reserves_raw is None
        or reserves_trade.quote_reserves_raw is None
        or reserves_trade.base_reserves_raw <= 0
        or reserves_trade.quote_reserves_raw <= 0
    ):
        return None
    if size_sol <= 0:
        raise ValueError("size_sol must be positive")

    quote_in_raw = size_sol * 10**quote_decimals
    effective_quote_in_raw = quote_in_raw * (1 - cost_model.total_fee_pct / 100)
    if effective_quote_in_raw <= 0:
        return None
    base_out_raw = _constant_product_buy_base_out_raw(
        base_reserves_raw=reserves_trade.base_reserves_raw,
        quote_reserves_raw=reserves_trade.quote_reserves_raw,
        effective_quote_in_raw=effective_quote_in_raw,
    )
    if base_out_raw <= 0:
        return None
    base_out = base_out_raw / 10**base_decimals
    return size_sol / base_out


def simulate_amm_sell_execution_price_sol(
    *,
    reserves_trade: PathTrade,
    size_tokens: float,
    cost_model: CostModel,
    base_decimals: int = DEFAULT_BASE_DECIMALS,
    quote_decimals: int = DEFAULT_QUOTE_DECIMALS,
) -> float | None:
    """Average execution price (SOL per token) for a hypothetical sell of
    `size_tokens`, simulated against `reserves_trade`'s post-trade reserves."""

    if (
        reserves_trade.base_reserves_raw is None
        or reserves_trade.quote_reserves_raw is None
        or reserves_trade.base_reserves_raw <= 0
        or reserves_trade.quote_reserves_raw <= 0
    ):
        return None
    if size_tokens <= 0:
        raise ValueError("size_tokens must be positive")

    base_in_raw = size_tokens * 10**base_decimals
    quote_out_raw_gross = _constant_product_sell_quote_out_raw(
        base_reserves_raw=reserves_trade.base_reserves_raw,
        quote_reserves_raw=reserves_trade.quote_reserves_raw,
        base_in_raw=base_in_raw,
    )
    quote_out_raw_net = quote_out_raw_gross * (1 - cost_model.total_fee_pct / 100)
    if quote_out_raw_net <= 0:
        return None
    quote_out = quote_out_raw_net / 10**quote_decimals
    return quote_out / size_tokens


@dataclass(frozen=True)
class CausalEntry:
    signal_time: int
    entry_latency_seconds: int
    size_sol: float
    trade_chain_time: int | None
    trade_venue: str | None
    mid_price_sol: float | None
    execution_price_sol: float | None
    missing_reason: str | None


def find_causal_entry(
    trades: Sequence[PathTrade],
    *,
    signal_time: int,
    entry_latency_seconds: int,
    size_sol: float,
    cost_model: CostModel,
    base_decimals: int = DEFAULT_BASE_DECIMALS,
    quote_decimals: int = DEFAULT_QUOTE_DECIMALS,
) -> CausalEntry:
    """First trade at or after signal_time + entry_latency_seconds. Only that one
    trade's data is ever used -- nothing strictly after it can change the result
    (see test_entry_is_unaffected_by_shuffling_or_altering_future_trades)."""

    if entry_latency_seconds < 0:
        raise ValueError("entry_latency_seconds cannot be negative")
    if size_sol <= 0:
        raise ValueError("size_sol must be positive")

    threshold = signal_time + entry_latency_seconds
    candidates = [t for t in trades if t.chain_time >= threshold]
    if not candidates:
        return CausalEntry(
            signal_time=signal_time,
            entry_latency_seconds=entry_latency_seconds,
            size_sol=size_sol,
            trade_chain_time=None,
            trade_venue=None,
            mid_price_sol=None,
            execution_price_sol=None,
            missing_reason="no_trade_at_or_after_entry_time",
        )

    entry_trade = min(candidates, key=lambda t: t.chain_time)
    mid = mid_price_sol(entry_trade, base_decimals=base_decimals, quote_decimals=quote_decimals)
    execution_price = simulate_amm_buy_execution_price_sol(
        reserves_trade=entry_trade,
        size_sol=size_sol,
        cost_model=cost_model,
        base_decimals=base_decimals,
        quote_decimals=quote_decimals,
    )
    missing_reason = None if execution_price is not None else "entry_trade_missing_reserves"

    return CausalEntry(
        signal_time=signal_time,
        entry_latency_seconds=entry_latency_seconds,
        size_sol=size_sol,
        trade_chain_time=entry_trade.chain_time,
        trade_venue=entry_trade.venue,
        mid_price_sol=mid,
        execution_price_sol=execution_price,
        missing_reason=missing_reason,
    )


@dataclass(frozen=True)
class WindowMetrics:
    window_seconds: int
    n_trades_in_window: int
    mfe_pct: float | None
    """Theoretical ceiling (hindsight). Never an edge metric -- see module docstring."""
    time_to_mfe_seconds: int | None
    mae_pct: float | None
    time_to_mae_seconds: int | None
    return_at_window_end_pct: float | None
    max_internal_gap_seconds: int
    flags: tuple[str, ...]


def compute_window_metrics(
    trades: Sequence[PathTrade],
    *,
    entry_chain_time: int,
    entry_execution_price_sol: float,
    window_seconds: int,
    base_decimals: int = DEFAULT_BASE_DECIMALS,
    quote_decimals: int = DEFAULT_QUOTE_DECIMALS,
    gap_flag_seconds: int = DEFAULT_GAP_FLAG_SECONDS,
    migration_discontinuity_flag_pct: float = DEFAULT_MIGRATION_DISCONTINUITY_FLAG_PCT,
) -> WindowMetrics:
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    if entry_execution_price_sol <= 0:
        raise ValueError("entry_execution_price_sol must be positive")

    window_end = entry_chain_time + window_seconds
    in_window = sorted(
        (t for t in trades if entry_chain_time <= t.chain_time <= window_end),
        key=lambda t: t.chain_time,
    )
    if not in_window:
        return WindowMetrics(
            window_seconds=window_seconds,
            n_trades_in_window=0,
            mfe_pct=None,
            time_to_mfe_seconds=None,
            mae_pct=None,
            time_to_mae_seconds=None,
            return_at_window_end_pct=None,
            max_internal_gap_seconds=0,
            flags=("no_trades_in_window",),
        )

    priced: list[tuple[int, float, str]] = []
    for trade in in_window:
        price = executed_trade_price_sol(
            trade, base_decimals=base_decimals, quote_decimals=quote_decimals
        )
        if price is not None:
            priced.append((trade.chain_time, price, trade.venue))

    flags: list[str] = []
    if not priced:
        return WindowMetrics(
            window_seconds=window_seconds,
            n_trades_in_window=len(in_window),
            mfe_pct=None,
            time_to_mfe_seconds=None,
            mae_pct=None,
            time_to_mae_seconds=None,
            return_at_window_end_pct=None,
            max_internal_gap_seconds=0,
            flags=("no_price_derivable_in_window",),
        )

    mfe_pct = time_to_mfe = mae_pct = time_to_mae = None
    for chain_time, price, _venue in priced:
        ret_pct = (price / entry_execution_price_sol - 1) * 100
        if mfe_pct is None or ret_pct > mfe_pct:
            mfe_pct, time_to_mfe = ret_pct, chain_time - entry_chain_time
        if mae_pct is None or ret_pct < mae_pct:
            mae_pct, time_to_mae = ret_pct, chain_time - entry_chain_time

    last_time, last_price, _ = priced[-1]
    return_at_end = (last_price / entry_execution_price_sol - 1) * 100
    if last_time < window_end:
        flags.append(f"price_stale_at_window_end:{window_end - last_time}s")

    max_gap = 0
    for (t1, _, _), (t2, _, _) in zip(priced, priced[1:]):
        max_gap = max(max_gap, t2 - t1)
    if max_gap > gap_flag_seconds:
        flags.append(f"internal_gap_exceeds_threshold:{max_gap}s")

    venues_seen = {venue for _, _, venue in priced}
    if len(venues_seen) > 1:
        flags.append("venue_migration_in_window")
        for (_, p1, v1), (_, p2, v2) in zip(priced, priced[1:]):
            if v1 != v2 and p1 > 0:
                jump_pct = abs(p2 / p1 - 1) * 100
                if jump_pct > migration_discontinuity_flag_pct:
                    flags.append(f"price_discontinuity_at_migration:{jump_pct:.1f}pct")

    return WindowMetrics(
        window_seconds=window_seconds,
        n_trades_in_window=len(in_window),
        mfe_pct=mfe_pct,
        time_to_mfe_seconds=time_to_mfe,
        mae_pct=mae_pct,
        time_to_mae_seconds=time_to_mae,
        return_at_window_end_pct=return_at_end,
        max_internal_gap_seconds=max_gap,
        flags=tuple(flags),
    )


def first_barrier_touch(
    trades: Sequence[PathTrade],
    *,
    entry_chain_time: int,
    entry_execution_price_sol: float,
    window_seconds: int,
    target_pct: float,
    stop_pct: float,
    base_decimals: int = DEFAULT_BASE_DECIMALS,
    quote_decimals: int = DEFAULT_QUOTE_DECIMALS,
) -> str:
    """Returns "UP" (target touched first), "DOWN" (stop touched first), or
    "NONE" (neither touched within window_seconds)."""

    if target_pct <= 0:
        raise ValueError("target_pct must be positive")
    if stop_pct >= 0:
        raise ValueError("stop_pct must be negative")

    window_end = entry_chain_time + window_seconds
    in_window = sorted(
        (t for t in trades if entry_chain_time < t.chain_time <= window_end),
        key=lambda t: t.chain_time,
    )
    for trade in in_window:
        price = executed_trade_price_sol(
            trade, base_decimals=base_decimals, quote_decimals=quote_decimals
        )
        if price is None:
            continue
        ret_pct = (price / entry_execution_price_sol - 1) * 100
        if ret_pct >= target_pct:
            return "UP"
        if ret_pct <= stop_pct:
            return "DOWN"
    return "NONE"


# -- Fixed exit library (max 6, per the work order) --------------------------

EXIT_RULE_TP50_SL30 = "tp50_sl30_v0"
EXIT_RULE_TRAIL20_AFTER20 = "trail20_after_plus20_v0"
EXIT_RULE_TIME_STOP_5M = "time_stop_5m_v0"
EXIT_RULE_PARTIAL50_AT50_TRAIL20 = "partial50_at_plus50_trail20_v0"
EXIT_RULE_HOLD_UNTIL_WINDOW_END = "hold_until_window_end_v0"
EXIT_RULE_TP100_SL50 = "tp100_sl50_v0"

EXIT_RULE_IDS: tuple[str, ...] = (
    EXIT_RULE_TP50_SL30,
    EXIT_RULE_TRAIL20_AFTER20,
    EXIT_RULE_TIME_STOP_5M,
    EXIT_RULE_PARTIAL50_AT50_TRAIL20,
    EXIT_RULE_HOLD_UNTIL_WINDOW_END,
    EXIT_RULE_TP100_SL50,
)


@dataclass(frozen=True)
class ExitResult:
    rule_id: str
    exit_latency_seconds: int
    trigger_chain_time: int | None
    exit_chain_time: int | None
    exit_reason: str | None
    gross_return_pct: float | None
    """Return from entry execution price to exit execution price, before the
    flat network/ATA leg cost. Still net of venue+terminal fee and slippage on
    both legs, which are baked into the execution prices themselves."""
    net_return_pct: float | None
    """gross_return_pct minus the flat per-leg network/ATA cost, expressed as a
    percentage of position size."""
    missing_reason: str | None


def _causal_exit_trade(
    trades: Sequence[PathTrade], *, trigger_time: int, exit_latency_seconds: int
) -> PathTrade | None:
    threshold = trigger_time + exit_latency_seconds
    candidates = [t for t in trades if t.chain_time >= threshold]
    if not candidates:
        return None
    return min(candidates, key=lambda t: t.chain_time)


def _flat_leg_cost_pct(cost_model: CostModel, *, size_sol: float, n_legs: int) -> float:
    flat_cost_sol = (cost_model.network_fee_sol + cost_model.ata_fee_sol) * n_legs
    return (flat_cost_sol / size_sol) * 100


def _scan_returns(
    trades: Sequence[PathTrade],
    *,
    entry_chain_time: int,
    entry_execution_price_sol: float,
    window_end: int,
    base_decimals: int,
    quote_decimals: int,
) -> list[tuple[int, float]]:
    in_window = sorted(
        (t for t in trades if entry_chain_time < t.chain_time <= window_end),
        key=lambda t: t.chain_time,
    )
    out = []
    for trade in in_window:
        price = executed_trade_price_sol(
            trade, base_decimals=base_decimals, quote_decimals=quote_decimals
        )
        if price is not None:
            out.append((trade.chain_time, (price / entry_execution_price_sol - 1) * 100))
    return out


def simulate_exit(
    trades: Sequence[PathTrade],
    *,
    rule_id: str,
    entry_chain_time: int,
    entry_execution_price_sol: float,
    size_sol: float,
    window_seconds: int,
    exit_latency_seconds: int,
    cost_model: CostModel,
    base_decimals: int = DEFAULT_BASE_DECIMALS,
    quote_decimals: int = DEFAULT_QUOTE_DECIMALS,
) -> ExitResult:
    """Causally simulate one of the EXIT_RULE_IDS. The trigger is found by
    scanning trades strictly after entry; the actual exit then executes at the
    first trade at/after trigger_time + exit_latency_seconds (same causal-
    latency discipline as entry), with its own AMM slippage + fees."""

    if rule_id not in EXIT_RULE_IDS:
        raise ValueError(f"unknown exit rule: {rule_id}")
    if exit_latency_seconds < 0:
        raise ValueError("exit_latency_seconds cannot be negative")

    window_end = entry_chain_time + window_seconds
    returns = _scan_returns(
        trades,
        entry_chain_time=entry_chain_time,
        entry_execution_price_sol=entry_execution_price_sol,
        window_end=window_end,
        base_decimals=base_decimals,
        quote_decimals=quote_decimals,
    )

    trigger_time: int | None = None
    reason: str | None = None

    if rule_id in (EXIT_RULE_TP50_SL30, EXIT_RULE_TP100_SL50):
        target_pct, stop_pct = (50.0, -30.0) if rule_id == EXIT_RULE_TP50_SL30 else (100.0, -50.0)
        for chain_time, ret_pct in returns:
            if ret_pct >= target_pct:
                trigger_time, reason = chain_time, "take_profit"
                break
            if ret_pct <= stop_pct:
                trigger_time, reason = chain_time, "stop_loss"
                break

    elif rule_id == EXIT_RULE_TRAIL20_AFTER20:
        armed = False
        peak_ret = None
        for chain_time, ret_pct in returns:
            if not armed and ret_pct >= 20.0:
                armed = True
                peak_ret = ret_pct
            elif armed:
                peak_ret = max(peak_ret, ret_pct)
                drawdown_from_peak_pct = peak_ret - ret_pct
                if drawdown_from_peak_pct >= 20.0:
                    trigger_time, reason = chain_time, "trailing_stop"
                    break

    elif rule_id == EXIT_RULE_TIME_STOP_5M:
        fixed_trigger = entry_chain_time + 5 * 60
        if fixed_trigger <= window_end:
            trigger_time, reason = fixed_trigger, "time_stop_5m"

    elif rule_id == EXIT_RULE_PARTIAL50_AT50_TRAIL20:
        # Simplified single-trigger model: the +50% partial-sell point also
        # starts the trailing stop on the remainder. If +50% is never reached,
        # this degrades to hold_until_window_end on the full position -- there
        # is no separate rule for that fallback; it is this rule's own tail.
        armed = False
        peak_ret = None
        for chain_time, ret_pct in returns:
            if not armed and ret_pct >= 50.0:
                armed = True
                peak_ret = ret_pct
                trigger_time, reason = chain_time, "partial_take_profit_50"
                # Partial exit is a real event; continue scanning for the
                # trailing leg on the remainder so the final `reason` can
                # upgrade to the trailing exit if it fires before window end.
            elif armed:
                peak_ret = max(peak_ret, ret_pct)
                drawdown_from_peak_pct = peak_ret - ret_pct
                if drawdown_from_peak_pct >= 20.0:
                    trigger_time, reason = chain_time, "trailing_stop_on_remainder"
                    break

    elif rule_id == EXIT_RULE_HOLD_UNTIL_WINDOW_END:
        pass  # trigger_time stays None -> falls through to the window-end exit below.

    if trigger_time is None:
        if not returns:
            return ExitResult(
                rule_id=rule_id,
                exit_latency_seconds=exit_latency_seconds,
                trigger_chain_time=None,
                exit_chain_time=None,
                exit_reason=None,
                gross_return_pct=None,
                net_return_pct=None,
                missing_reason="no_priced_trades_after_entry",
            )
        trigger_time, reason = returns[-1][0], "hold_to_window_end"

    exit_trade = _causal_exit_trade(
        trades, trigger_time=trigger_time, exit_latency_seconds=exit_latency_seconds
    )
    if exit_trade is None:
        return ExitResult(
            rule_id=rule_id,
            exit_latency_seconds=exit_latency_seconds,
            trigger_chain_time=trigger_time,
            exit_chain_time=None,
            exit_reason=reason,
            gross_return_pct=None,
            net_return_pct=None,
            missing_reason="no_trade_at_or_after_exit_latency",
        )

    size_tokens = size_sol / entry_execution_price_sol
    exit_price = simulate_amm_sell_execution_price_sol(
        reserves_trade=exit_trade,
        size_tokens=size_tokens,
        cost_model=cost_model,
        base_decimals=base_decimals,
        quote_decimals=quote_decimals,
    )
    if exit_price is None:
        return ExitResult(
            rule_id=rule_id,
            exit_latency_seconds=exit_latency_seconds,
            trigger_chain_time=trigger_time,
            exit_chain_time=exit_trade.chain_time,
            exit_reason=reason,
            gross_return_pct=None,
            net_return_pct=None,
            missing_reason="exit_trade_missing_reserves",
        )

    gross_return_pct = (exit_price / entry_execution_price_sol - 1) * 100
    net_return_pct = gross_return_pct - _flat_leg_cost_pct(cost_model, size_sol=size_sol, n_legs=2)

    return ExitResult(
        rule_id=rule_id,
        exit_latency_seconds=exit_latency_seconds,
        trigger_chain_time=trigger_time,
        exit_chain_time=exit_trade.chain_time,
        exit_reason=reason,
        gross_return_pct=gross_return_pct,
        net_return_pct=net_return_pct,
        missing_reason=None,
    )
