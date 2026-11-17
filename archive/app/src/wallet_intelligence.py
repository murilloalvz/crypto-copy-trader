from collections import Counter
from dataclasses import dataclass
from statistics import median

from src.discovery.models import WalletHistory, WalletPositions


@dataclass(frozen=True)
class WalletIntelligencePolicy:
    """Conservative research gates; none of them authorize trading."""

    min_position_sample: int = 10
    min_onchain_swaps: int = 20
    min_copyable_hold_seconds: float = 300.0
    min_liquidity_coverage_pct: float = 60.0
    min_liquid_capital_share_pct: float = 60.0
    min_token_liquidity_usd: float = 50_000.0
    max_top_winner_share_pct: float = 40.0


@dataclass(frozen=True)
class WalletStrategyProfile:
    address: str
    sample_grade: str
    archetype: str
    execution_style: str
    sampled_positions: int
    winners: int
    losers: int
    win_rate_pct: float
    realized_pnl_usd: float
    median_position_pnl_usd: float
    median_roi_pct: float
    profit_factor: float | None
    top_winner_share_pct: float
    top3_winner_share_pct: float
    pnl_without_top_winner_usd: float
    best_position_pnl_usd: float
    worst_position_pnl_usd: float
    median_invested_usd: float
    median_hold_seconds: float | None
    p25_hold_seconds: float | None
    p75_hold_seconds: float | None
    median_actions_per_token: float
    multi_action_position_share_pct: float
    liquidity_coverage_pct: float
    liquid_position_share_pct: float
    liquid_capital_share_pct: float
    median_current_liquidity_usd: float
    median_current_market_cap_usd: float
    microcap_position_share_pct: float
    smallcap_position_share_pct: float
    active_days: int
    profitable_days: int
    losing_days: int
    median_daily_pnl_usd: float
    top_positive_day_share_pct: float
    realized_daily_drawdown_usd: float
    local_swap_count: int
    local_token_count: int
    local_buy_count: int
    local_sell_count: int
    local_roundtrip_token_share_pct: float
    local_multi_action_token_share_pct: float
    median_local_swap_gap_seconds: float | None
    dex_mix: dict[str, int]
    delay_research_ready: bool
    flags: tuple[str, ...]
    limitations: tuple[str, ...]


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


def _sample_grade(count: int) -> str:
    if count < 10:
        return "INSUFFICIENT"
    if count < 30:
        return "PRELIMINARY"
    if count < 100:
        return "DEVELOPING"
    return "LARGER_SAMPLE"


def _archetype(median_hold_seconds: float | None) -> str:
    if median_hold_seconds is None:
        return "unknown"
    if median_hold_seconds < 300:
        return "ultra_short"
    if median_hold_seconds < 1_800:
        return "short_term_scalper"
    if median_hold_seconds < 21_600:
        return "intraday"
    if median_hold_seconds < 259_200:
        return "swing"
    return "position"


def _daily_metrics(history: WalletHistory) -> dict:
    active = [item for item in history.days if item.trades > 0]
    pnl = [float(item.realized_pnl_usd) for item in active]
    positive = [max(value, 0.0) for value in pnl]
    gross_positive = sum(positive)
    top_positive_share = (
        100 * max(positive, default=0.0) / gross_positive
        if gross_positive > 0
        else 0.0
    )
    curve = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in pnl:
        curve += value
        peak = max(peak, curve)
        drawdown = max(drawdown, peak - curve)
    return {
        "active_days": len(active),
        "profitable_days": sum(value > 0 for value in pnl),
        "losing_days": sum(value < 0 for value in pnl),
        "median_daily_pnl_usd": median(pnl) if pnl else 0.0,
        "top_positive_day_share_pct": top_positive_share,
        "realized_daily_drawdown_usd": drawdown,
    }


def _local_swap_metrics(onchain_swaps: list[dict]) -> dict:
    swaps = [
        item
        for item in onchain_swaps
        if item.get("kind") == "swap"
        and item.get("status") == "success"
        and item.get("token_mint")
        and item.get("token_change") is not None
    ]
    swaps.sort(key=lambda item: int(item.get("block_time") or 0))
    per_token: dict[str, list[dict]] = {}
    for item in swaps:
        per_token.setdefault(str(item["token_mint"]), []).append(item)
    roundtrips = 0
    multi_action = 0
    for token_swaps in per_token.values():
        has_buy = any(float(item["token_change"]) > 0 for item in token_swaps)
        has_sell = any(float(item["token_change"]) < 0 for item in token_swaps)
        roundtrips += has_buy and has_sell
        multi_action += len(token_swaps) > 2
    token_count = len(per_token)
    times = [int(item.get("block_time") or 0) for item in swaps if item.get("block_time")]
    gaps = [
        float(current - previous)
        for previous, current in zip(times, times[1:])
        if current >= previous
    ]
    dex_mix = Counter(str(item.get("dex") or "unknown") for item in swaps)
    return {
        "swap_count": len(swaps),
        "token_count": token_count,
        "buy_count": sum(float(item["token_change"]) > 0 for item in swaps),
        "sell_count": sum(float(item["token_change"]) < 0 for item in swaps),
        "roundtrip_share_pct": 100 * roundtrips / token_count if token_count else 0.0,
        "multi_action_share_pct": 100 * multi_action / token_count if token_count else 0.0,
        "median_gap_seconds": median(gaps) if gaps else None,
        "dex_mix": dict(dex_mix.most_common()),
    }


def _execution_style(local_metrics: dict) -> str:
    if local_metrics["swap_count"] == 0:
        return "unknown_without_onchain_sequence"
    if local_metrics["multi_action_share_pct"] >= 40:
        return "scaled_or_multi_leg"
    if (
        local_metrics["roundtrip_share_pct"] >= 60
        and local_metrics["multi_action_share_pct"] < 20
    ):
        return "mostly_single_roundtrips"
    return "mixed_or_incomplete"


def build_wallet_strategy_profile(
    address: str,
    history: WalletHistory,
    positions: WalletPositions,
    onchain_swaps: list[dict] | None = None,
    policy: WalletIntelligencePolicy | None = None,
) -> WalletStrategyProfile:
    """Build a descriptive research profile without changing any strategy."""

    policy = policy or WalletIntelligencePolicy()
    sampled = list(positions.positions)
    pnl_values = [float(item.realized_pnl_usd) for item in sampled]
    roi_values = [float(item.roi_pct) for item in sampled]
    invested_values = [max(float(item.invested_usd), 0.0) for item in sampled]
    winners = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value < 0]
    gross_profit = sum(winners)
    gross_loss = abs(sum(losses))
    best = max(pnl_values, default=0.0)
    worst = min(pnl_values, default=0.0)
    realized = sum(pnl_values)
    top_winners = sorted(winners, reverse=True)
    top_share = 100 * top_winners[0] / gross_profit if gross_profit else 0.0
    top3_share = 100 * sum(top_winners[:3]) / gross_profit if gross_profit else 0.0
    pnl_without_best = realized - max(best, 0.0)

    hold_values = [
        float(item.hold_time_seconds)
        for item in sampled
        if item.hold_time_seconds is not None and item.hold_time_seconds >= 0
    ]
    action_values = [max(float(item.trades), 0.0) for item in sampled]
    multi_action_share = (
        100 * sum(item.trades > 2 for item in sampled) / len(sampled)
        if sampled
        else 0.0
    )

    known_liquidity = [
        item
        for item in sampled
        if item.liquidity_usd is not None and item.liquidity_usd >= 0
    ]
    liquid = [
        item
        for item in known_liquidity
        if float(item.liquidity_usd or 0) >= policy.min_token_liquidity_usd
    ]
    sampled_invested = sum(invested_values)
    liquid_invested = sum(max(float(item.invested_usd), 0.0) for item in liquid)
    liquidity_values = [float(item.liquidity_usd or 0.0) for item in known_liquidity]
    market_caps = [
        float(item.market_cap_usd)
        for item in sampled
        if item.market_cap_usd is not None and item.market_cap_usd >= 0
    ]
    microcap_share = (
        100
        * sum(
            item.market_cap_usd is not None and 0 <= item.market_cap_usd < 2_000_000
            for item in sampled
        )
        / len(sampled)
        if sampled
        else 0.0
    )
    smallcap_share = (
        100
        * sum(
            item.market_cap_usd is not None
            and 2_000_000 <= item.market_cap_usd < 20_000_000
            for item in sampled
        )
        / len(sampled)
        if sampled
        else 0.0
    )

    liquidity_coverage = (
        100 * len(known_liquidity) / len(sampled) if sampled else 0.0
    )
    liquid_position_share = (
        100 * len(liquid) / len(known_liquidity) if known_liquidity else 0.0
    )
    liquid_capital_share = (
        100 * liquid_invested / sampled_invested if sampled_invested > 0 else 0.0
    )
    median_hold = median(hold_values) if hold_values else None
    daily = _daily_metrics(history)
    local = _local_swap_metrics(onchain_swaps or [])

    flags = []
    if len(sampled) < policy.min_position_sample:
        flags.append("position_sample_too_small")
    if top_share > policy.max_top_winner_share_pct:
        flags.append("profit_concentrated_in_top_winner")
    if realized > 0 and pnl_without_best <= 0:
        flags.append("positive_pnl_disappears_without_best_position")
    if realized > 0 and roi_values and median(roi_values) <= 0:
        flags.append("positive_pnl_with_nonpositive_median_roi")
    if median_hold is None:
        flags.append("hold_time_unavailable")
    elif median_hold < policy.min_copyable_hold_seconds:
        flags.append("holding_time_too_short_for_delayed_copy")
    if liquidity_coverage < policy.min_liquidity_coverage_pct:
        flags.append("liquidity_coverage_low")
    if liquid_capital_share < policy.min_liquid_capital_share_pct:
        flags.append("liquid_capital_share_low")
    if local["swap_count"] < policy.min_onchain_swaps:
        flags.append("onchain_sequence_sample_small")

    severe_delay_flags = {
        "position_sample_too_small",
        "holding_time_too_short_for_delayed_copy",
        "hold_time_unavailable",
        "liquidity_coverage_low",
        "liquid_capital_share_low",
    }
    delay_research_ready = not severe_delay_flags.intersection(flags)

    limitations = (
        "Liquidez e market cap das posições são fotografias atuais, não o estado no instante da entrada.",
        "Histórico do Solana Tracker é agregado por dia; ele não reconstrói sozinho a ordem exata das compras e vendas.",
        "A sequência on-chain local depende da profundidade já sincronizada no SQLite e pode ser parcial.",
        "Candles de 1 minuto não distinguem de forma confiável atrasos de 15s e 30s; a análise de latência precisa de quotes/ticks mais finos.",
        "Este perfil é descritivo e não autoriza alteração da wave_v3 nem execução real.",
    )

    return WalletStrategyProfile(
        address=address,
        sample_grade=_sample_grade(len(sampled)),
        archetype=_archetype(median_hold),
        execution_style=_execution_style(local),
        sampled_positions=len(sampled),
        winners=len(winners),
        losers=len(losses),
        win_rate_pct=100 * len(winners) / (len(winners) + len(losses))
        if winners or losses
        else 0.0,
        realized_pnl_usd=realized,
        median_position_pnl_usd=median(pnl_values) if pnl_values else 0.0,
        median_roi_pct=median(roi_values) if roi_values else 0.0,
        profit_factor=gross_profit / gross_loss if gross_loss > 0 else None,
        top_winner_share_pct=top_share,
        top3_winner_share_pct=top3_share,
        pnl_without_top_winner_usd=pnl_without_best,
        best_position_pnl_usd=best,
        worst_position_pnl_usd=worst,
        median_invested_usd=median(invested_values) if invested_values else 0.0,
        median_hold_seconds=median_hold,
        p25_hold_seconds=_percentile(hold_values, 0.25),
        p75_hold_seconds=_percentile(hold_values, 0.75),
        median_actions_per_token=median(action_values) if action_values else 0.0,
        multi_action_position_share_pct=multi_action_share,
        liquidity_coverage_pct=liquidity_coverage,
        liquid_position_share_pct=liquid_position_share,
        liquid_capital_share_pct=liquid_capital_share,
        median_current_liquidity_usd=median(liquidity_values) if liquidity_values else 0.0,
        median_current_market_cap_usd=median(market_caps) if market_caps else 0.0,
        microcap_position_share_pct=microcap_share,
        smallcap_position_share_pct=smallcap_share,
        active_days=daily["active_days"],
        profitable_days=daily["profitable_days"],
        losing_days=daily["losing_days"],
        median_daily_pnl_usd=daily["median_daily_pnl_usd"],
        top_positive_day_share_pct=daily["top_positive_day_share_pct"],
        realized_daily_drawdown_usd=daily["realized_daily_drawdown_usd"],
        local_swap_count=local["swap_count"],
        local_token_count=local["token_count"],
        local_buy_count=local["buy_count"],
        local_sell_count=local["sell_count"],
        local_roundtrip_token_share_pct=local["roundtrip_share_pct"],
        local_multi_action_token_share_pct=local["multi_action_share_pct"],
        median_local_swap_gap_seconds=local["median_gap_seconds"],
        dex_mix=local["dex_mix"],
        delay_research_ready=delay_research_ready,
        flags=tuple(flags),
        limitations=limitations,
    )


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "indisponível"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3_600:
        return f"{seconds / 60:.1f}min"
    if seconds < 86_400:
        return f"{seconds / 3_600:.1f}h"
    return f"{seconds / 86_400:.1f}d"
