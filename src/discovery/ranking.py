import math
from collections import Counter
from dataclasses import dataclass

from src.discovery.models import (
    CandidateInput,
    CandidateResult,
    LeaderboardWallet,
    WalletPeriodMetrics,
)


@dataclass(frozen=True)
class CandidatePolicy:
    min_trades_30d: int = 20
    max_trades_30d: int = 1_000
    min_win_rate_pct: float = 45.0
    min_realized_outcomes: int = 5
    min_unique_tokens: int = 3
    min_trades_7d: int = 1


REJECTION_LABELS = {
    "source_pnl_non_positive": "PnL do leaderboard não positivo",
    "source_too_few_trades": "menos de 20 trades no leaderboard",
    "source_too_many_trades": "mais de 1000 trades no leaderboard",
    "pnl_non_positive": "PnL realizado 30d não positivo",
    "roi_non_positive": "ROI realizado 30d não positivo",
    "too_few_trades": "menos de 20 trades em 30d",
    "too_many_trades": "mais de 1000 trades em 30d",
    "win_rate_below_minimum": "win rate abaixo de 45%",
    "too_few_realized_outcomes": "menos de 5 resultados realizados",
    "too_few_tokens": "menos de 3 tokens no período",
    "inactive_7d": "nenhum trade nos últimos 7 dias",
}


def prefilter_leaderboard(
    wallet: LeaderboardWallet, policy: CandidatePolicy
) -> tuple[str, ...]:
    reasons = []
    if wallet.pnl_usd <= 0:
        reasons.append("source_pnl_non_positive")
    if wallet.trade_count < policy.min_trades_30d:
        reasons.append("source_too_few_trades")
    if wallet.trade_count > policy.max_trades_30d:
        reasons.append("source_too_many_trades")
    return tuple(reasons)


def filter_30d(
    metrics: WalletPeriodMetrics, policy: CandidatePolicy
) -> tuple[str, ...]:
    reasons = []
    if metrics.realized_pnl_usd <= 0:
        reasons.append("pnl_non_positive")
    if metrics.roi_pct <= 0:
        reasons.append("roi_non_positive")
    if metrics.total_trade < policy.min_trades_30d:
        reasons.append("too_few_trades")
    if metrics.total_trade > policy.max_trades_30d:
        reasons.append("too_many_trades")
    if metrics.win_rate_pct < policy.min_win_rate_pct:
        reasons.append("win_rate_below_minimum")
    if metrics.realized_outcomes < policy.min_realized_outcomes:
        reasons.append("too_few_realized_outcomes")
    if metrics.unique_tokens < policy.min_unique_tokens:
        reasons.append("too_few_tokens")
    return tuple(reasons)


def filter_recent(
    metrics: WalletPeriodMetrics, policy: CandidatePolicy
) -> tuple[str, ...]:
    return ("inactive_7d",) if metrics.total_trade < policy.min_trades_7d else ()


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _sample_quality(trades: int) -> float:
    if trades < 20:
        return 0.0
    if trades < 50:
        return 0.5 + 0.5 * (trades - 20) / 30
    if trades <= 300:
        return 1.0
    return 1.0 - 0.7 * _clamp((trades - 300) / 700)


def _percentile_ranks(values: list[float]) -> list[float]:
    if len(values) <= 1:
        return [0.5] * len(values)
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index
        while end + 1 < len(order) and values[order[end + 1]] == values[order[index]]:
            end += 1
        average_rank = (index + end) / 2
        percentile = average_rank / (len(values) - 1)
        for position in range(index, end + 1):
            ranks[order[position]] = percentile
        index = end + 1
    return ranks


def _score_one(candidate: CandidateInput, pnl_percentile: float) -> CandidateResult:
    m30 = candidate.metrics_30d
    m7 = candidate.metrics_7d
    m90 = candidate.metrics_90d

    positive_periods = sum(
        metrics is not None and metrics.realized_pnl_usd > 0
        for metrics in (m7, m30, m90)
    )
    consistency = 25 * positive_periods / 3
    profitability = 20 * _clamp(math.log1p(max(m30.roi_pct, 0)) / math.log1p(100))
    sample = 15 * _sample_quality(m30.total_trade)
    win_rate = 15 * (
        0.5 + 0.5 * _clamp((m30.win_rate_pct - 45) / 20)
    )
    activity = 10 * (
        0.3 + 0.7 * _clamp(math.log1p(m7.total_trade) / math.log1p(35))
    )
    diversity = 10 * _clamp(math.log1p(m30.unique_tokens) / math.log1p(15))
    pnl_rank = 5 * pnl_percentile

    components = {
        "consistency": consistency,
        "profitability": profitability,
        "sample": sample,
        "win_rate": win_rate,
        "recent_activity": activity,
        "token_diversity": diversity,
        "pnl_relative_rank": pnl_rank,
    }
    penalty_points = 0.0
    penalties = []
    if m30.total_trade > 300:
        points = 8 * _clamp((m30.total_trade - 300) / 700)
        penalty_points += points
        penalties.append(f"frequência 30d alta (-{points:.1f})")
    trades_per_day_7d = m7.total_trade / 7
    if trades_per_day_7d > 20:
        points = 5 * _clamp((trades_per_day_7d - 20) / 80)
        penalty_points += points
        penalties.append(f"ritmo recente difícil de copiar (-{points:.1f})")
    if m30.realized_outcomes < 10:
        points = 5 * (10 - m30.realized_outcomes) / 10
        penalty_points += points
        penalties.append(f"poucos resultados realizados (-{points:.1f})")

    score = round(_clamp(sum(components.values()) - penalty_points, 0, 100), 1)
    reasons = [
        f"ativa: {m7.total_trade} trades em 7d",
        f"amostra: {m30.total_trade} trades e {m30.unique_tokens} tokens em 30d",
        f"win rate: {m30.win_rate_pct:.1f}% em {m30.realized_outcomes} resultados",
        f"ROI realizado 30d: {m30.roi_pct:+.1f}%",
        f"PnL positivo em {positive_periods}/3 períodos",
    ]
    if m90 is None:
        reasons[-1] = f"PnL positivo em {positive_periods}/3 períodos (90d indisponível)"
    return CandidateResult(
        address=candidate.address,
        candidate_score=score,
        metrics_30d=m30,
        metrics_7d=m7,
        metrics_90d=m90,
        reasons=tuple(reasons),
        penalties=tuple(penalties),
        score_components={key: round(value, 2) for key, value in components.items()},
    )


def rank_candidates(candidates: list[CandidateInput]) -> list[CandidateResult]:
    """Rank candidates with capped, normalized metrics and basic copyability penalties."""
    pnl_values = [math.log1p(max(item.metrics_30d.realized_pnl_usd, 0)) for item in candidates]
    pnl_percentiles = _percentile_ranks(pnl_values)
    ranked = [
        _score_one(candidate, percentile)
        for candidate, percentile in zip(candidates, pnl_percentiles)
    ]
    return sorted(ranked, key=lambda item: (-item.candidate_score, item.address))


def rejection_summary(rejections: list[tuple[str, ...]]) -> dict[str, int]:
    counts = Counter(reason for group in rejections for reason in group)
    return dict(sorted(counts.items()))
