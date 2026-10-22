import math
from dataclasses import dataclass
from statistics import median

from src.discovery.models import (
    CandidateResult,
    CopyabilityMetrics,
    CopyabilityResult,
    WalletPositions,
)


@dataclass(frozen=True)
class CopyabilityPolicy:
    """Conservative defaults for a delayed, small-size copy-trading prototype."""

    position_sample_limit: int = 50
    min_sampled_positions: int = 5
    min_token_liquidity_usd: float = 50_000.0
    min_liquidity_coverage_pct: float = 60.0
    min_liquid_position_share_pct: float = 50.0
    min_liquid_capital_share_pct: float = 60.0
    min_average_hold_seconds: float = 300.0
    max_trades_per_day_30d: float = 20.0
    min_copyability_score: float = 60.0


COPYABILITY_REJECTION_LABELS = {
    "position_sample_too_small": "menos de 5 posições recentes na amostra",
    "position_pnl_mode_not_strict": "posições não retornadas em PnL estrito",
    "liquidity_coverage_low": "liquidez indisponível em mais de 40% dos tokens",
    "liquid_position_share_low": "menos de 50% dos tokens com liquidez mínima",
    "liquid_capital_share_low": "menos de 60% do capital em tokens líquidos",
    "average_hold_unavailable": "tempo médio de posição indisponível",
    "average_hold_too_short": "posição média inferior a 5 minutos",
    "trade_frequency_too_high": "mais de 20 trades por dia em 30d",
    "copyability_score_below_minimum": "Copyability Score abaixo de 60",
}


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _log_scale(value: float, floor: float, ceiling: float) -> float:
    if value <= floor:
        return 0.0
    if value >= ceiling:
        return 1.0
    return math.log(value / floor) / math.log(ceiling / floor)


def _holding_score(seconds: float | None) -> float:
    if seconds is None or seconds < 60:
        return 0.0
    if seconds < 300:
        return 0.1 + 0.3 * (seconds - 60) / 240
    if seconds < 1_800:
        return 0.4 + 0.6 * (seconds - 300) / 1_500
    return 1.0


def _frequency_score(trades_per_day: float) -> float:
    if trades_per_day <= 5:
        return 1.0
    if trades_per_day <= 15:
        return 1.0 - 0.5 * (trades_per_day - 5) / 10
    if trades_per_day <= 30:
        return 0.5 - 0.4 * (trades_per_day - 15) / 15
    return 0.0


def _entry_impact_score(ratio_pct: float | None) -> float:
    """Proxy only: wallet average buy size divided by current token liquidity."""
    if ratio_pct is None:
        return 0.0
    if ratio_pct <= 0.1:
        return 1.0
    if ratio_pct >= 2.0:
        return 0.0
    return 1.0 - (ratio_pct - 0.1) / 1.9


def calculate_copyability(
    candidate: CandidateResult,
    wallet_positions: WalletPositions,
    policy: CopyabilityPolicy | None = None,
) -> CopyabilityResult:
    """Score execution feasibility without mixing it into Candidate Score."""
    policy = policy or CopyabilityPolicy()
    positions = list(wallet_positions.positions[: policy.position_sample_limit])
    known = [
        item for item in positions
        if item.liquidity_usd is not None and item.liquidity_usd >= 0
    ]
    liquid = [
        item for item in known
        if (item.liquidity_usd or 0) >= policy.min_token_liquidity_usd
    ]
    invested = sum(max(item.invested_usd, 0) for item in positions)
    liquid_invested = sum(max(item.invested_usd, 0) for item in liquid)
    coverage_pct = 100 * len(known) / len(positions) if positions else 0.0
    liquid_position_share_pct = (
        100 * len(liquid) / len(known) if known else 0.0
    )
    liquid_capital_share_pct = (
        100 * liquid_invested / invested if invested > 0 else 0.0
    )
    liquidity_values = [item.liquidity_usd or 0 for item in known]
    entry_ratios = [
        100 * item.average_buy_usd / item.liquidity_usd
        for item in known
        if item.average_buy_usd is not None
        and item.average_buy_usd >= 0
        and item.liquidity_usd
        and item.liquidity_usd > 0
    ]
    signals = candidate.signals
    average_hold_seconds = signals.avg_hold_seconds if signals is not None else None
    trades_per_day = candidate.metrics_30d.total_trade / 30
    metrics = CopyabilityMetrics(
        sampled_positions=len(positions),
        known_liquidity_positions=len(known),
        liquid_positions=len(liquid),
        sampled_invested_usd=invested,
        liquid_invested_usd=liquid_invested,
        liquidity_coverage_pct=coverage_pct,
        liquid_position_share_pct=liquid_position_share_pct,
        liquid_capital_share_pct=liquid_capital_share_pct,
        median_liquidity_usd=median(liquidity_values) if liquidity_values else 0.0,
        median_entry_liquidity_ratio_pct=median(entry_ratios) if entry_ratios else None,
        trades_per_day_30d=trades_per_day,
        average_hold_seconds=average_hold_seconds,
    )
    components = {
        "liquid_capital": 30 * _clamp(liquid_capital_share_pct / 100),
        "typical_liquidity": 15 * _log_scale(
            metrics.median_liquidity_usd, 10_000, 500_000
        ),
        "entry_impact_proxy": 15 * _entry_impact_score(
            metrics.median_entry_liquidity_ratio_pct
        ),
        "holding_time": 20 * _holding_score(average_hold_seconds),
        "trade_frequency": 15 * _frequency_score(trades_per_day),
        "data_coverage": 5 * _clamp(coverage_pct / 100),
    }
    score = round(sum(components.values()), 1)
    rejections = []
    if len(positions) < policy.min_sampled_positions:
        rejections.append("position_sample_too_small")
    if wallet_positions.pnl_mode != "strict":
        rejections.append("position_pnl_mode_not_strict")
    if coverage_pct < policy.min_liquidity_coverage_pct:
        rejections.append("liquidity_coverage_low")
    if liquid_position_share_pct < policy.min_liquid_position_share_pct:
        rejections.append("liquid_position_share_low")
    if liquid_capital_share_pct < policy.min_liquid_capital_share_pct:
        rejections.append("liquid_capital_share_low")
    if average_hold_seconds is None:
        rejections.append("average_hold_unavailable")
    elif average_hold_seconds < policy.min_average_hold_seconds:
        rejections.append("average_hold_too_short")
    if trades_per_day > policy.max_trades_per_day_30d:
        rejections.append("trade_frequency_too_high")
    if score < policy.min_copyability_score:
        rejections.append("copyability_score_below_minimum")

    reasons = (
        f"{len(liquid)}/{len(known)} tokens conhecidos têm pelo menos "
        f"US$ {policy.min_token_liquidity_usd:,.0f} de liquidez atual",
        f"{liquid_capital_share_pct:.1f}% do capital amostrado está nesses tokens",
        f"liquidez mediana atual: US$ {metrics.median_liquidity_usd:,.0f}",
        f"ritmo: {trades_per_day:.1f} trades/dia em 30d",
    )
    return CopyabilityResult(
        candidate=candidate,
        copyability_score=score,
        passed=not rejections,
        metrics=metrics,
        reasons=reasons,
        rejection_reasons=tuple(rejections),
        score_components={key: round(value, 2) for key, value in components.items()},
    )


def rank_copyability(results: list[CopyabilityResult]) -> list[CopyabilityResult]:
    return sorted(
        results,
        key=lambda item: (
            not item.passed,
            -item.copyability_score,
            -item.candidate.candidate_score,
            item.candidate.address,
        ),
    )
