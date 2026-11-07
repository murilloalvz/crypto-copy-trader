import math
from collections import Counter
from dataclasses import dataclass

from src.discovery.models import (
    CandidateInput,
    CandidateResult,
    LeaderboardWallet,
    TraderSnapshot,
    WalletPeriodMetrics,
)


@dataclass(frozen=True)
class CandidatePolicy:
    min_trades_30d: int = 50
    max_trades_30d: int = 1_000
    min_win_rate_pct: float = 45.0
    min_realized_outcomes: int = 5
    min_unique_tokens: int = 3
    min_trades_7d: int = 1
    min_trading_days_30d: int = 10
    max_inactive_days: float = 7.0
    min_invested_usd_30d: float = 500.0
    min_avg_hold_seconds: float = 60.0
    max_single_token_profit_pct: float = 30.0


REJECTION_LABELS = {
    "source_pnl_non_positive": "PnL do leaderboard não positivo",
    "source_too_few_trades": "menos de 50 trades no leaderboard",
    "source_too_many_trades": "mais de 1000 trades no leaderboard",
    "pnl_non_positive": "PnL realizado 30d não positivo",
    "roi_non_positive": "ROI realizado 30d não positivo",
    "too_few_trades": "menos de 50 trades em 30d",
    "too_many_trades": "mais de 1000 trades em 30d",
    "win_rate_below_minimum": "win rate abaixo de 45%",
    "too_few_realized_outcomes": "menos de 5 resultados realizados",
    "too_few_tokens": "menos de 3 tokens no período",
    "inactive_7d": "nenhum trade nos últimos 7 dias",
    "too_few_trading_days": "menos de 10 dias ativos em 30d",
    "last_trade_unavailable": "data do último trade indisponível",
    "last_trade_too_old": "último trade há mais de 7 dias",
    "pnl_mode_not_strict": "PnL da fonte não está em modo estrito",
    "invested_below_minimum": "menos de US$ 500 investidos em 30d",
    "avg_hold_too_short": "posição média inferior a 60 segundos",
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


def filter_tracker_snapshot(
    snapshot: TraderSnapshot,
    policy: CandidatePolicy,
    *,
    now_ms: int,
) -> tuple[str, ...]:
    """Recheck server-side filters locally and add max-frequency/recency rules."""
    reasons = []
    if snapshot.realized_pnl_usd <= 0:
        reasons.append("pnl_non_positive")
    if snapshot.roi_pct <= 0:
        reasons.append("roi_non_positive")
    if snapshot.invested_usd < policy.min_invested_usd_30d:
        reasons.append("invested_below_minimum")
    if snapshot.trades < policy.min_trades_30d:
        reasons.append("too_few_trades")
    if snapshot.trades > policy.max_trades_30d:
        reasons.append("too_many_trades")
    if snapshot.win_rate_pct < policy.min_win_rate_pct:
        reasons.append("win_rate_below_minimum")
    if snapshot.closed_tokens < policy.min_realized_outcomes:
        reasons.append("too_few_realized_outcomes")
    if snapshot.tokens_traded < policy.min_unique_tokens:
        reasons.append("too_few_tokens")
    if snapshot.trading_days < policy.min_trading_days_30d:
        reasons.append("too_few_trading_days")
    if snapshot.last_trade_ms is None:
        reasons.append("last_trade_unavailable")
    elif max(0, now_ms - snapshot.last_trade_ms) / 86_400_000 > policy.max_inactive_days:
        reasons.append("last_trade_too_old")
    if snapshot.pnl_mode != "strict":
        reasons.append("pnl_mode_not_strict")
    return tuple(reasons)


def filter_candidate_signals(
    avg_hold_seconds: float | None, policy: CandidatePolicy
) -> tuple[str, ...]:
    """Reject only an observed, clearly uncopyable hold time; missing data stays unknown."""
    if (
        avg_hold_seconds is not None
        and avg_hold_seconds < policy.min_avg_hold_seconds
    ):
        return ("avg_hold_too_short",)
    return ()


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
    signals = candidate.signals
    if signals is None:
        components = {
            "consistency": 25 * positive_periods / 3,
            "profitability": 20 * _clamp(
                math.log1p(max(m30.roi_pct, 0)) / math.log1p(100)
            ),
            "sample": 15 * _sample_quality(m30.total_trade),
            "win_rate": 15 * (
                0.5 + 0.5 * _clamp((m30.win_rate_pct - 45) / 20)
            ),
            "recent_activity": 10 * (
                0.3 + 0.7 * _clamp(math.log1p(m7.total_trade) / math.log1p(35))
            ),
            "token_diversity": 10 * _clamp(
                math.log1p(m30.unique_tokens) / math.log1p(15)
            ),
            "pnl_relative_rank": 5 * pnl_percentile,
        }
    else:
        decided_days = signals.profitable_days_30d + signals.losing_days_30d
        profitable_day_ratio = (
            signals.profitable_days_30d / decided_days if decided_days else 0
        )
        components = {
            "consistency": 15 * positive_periods / 3 + 10 * profitable_day_ratio,
            "profitability": 15 * _clamp(
                math.log1p(max(m30.roi_pct, 0)) / math.log1p(100)
            ),
            "drawdown": 15 * (1 - _clamp(signals.realized_drawdown_pct / 50)),
            "sample": 15 * _sample_quality(m30.total_trade),
            "win_rate": 10 * (
                0.5 + 0.5 * _clamp((m30.win_rate_pct - 45) / 20)
            ),
            "recent_activity": 10 * (
                1 - 0.4 * _clamp(signals.last_trade_age_days / 7)
            ),
            "token_diversity": 5 * _clamp(
                math.log1p(m30.unique_tokens) / math.log1p(15)
            ),
            "pnl_relative_rank": 5 * pnl_percentile,
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
    if signals is not None and signals.top_positive_day_share_pct > 40:
        points = 8 * _clamp((signals.top_positive_day_share_pct - 40) / 60)
        penalty_points += points
        penalties.append(f"lucro diário concentrado (-{points:.1f})")
    if signals is not None and signals.avg_hold_seconds is not None:
        if signals.avg_hold_seconds < 60:
            points = 5.0
        elif signals.avg_hold_seconds < 300:
            points = 3.0
        elif signals.avg_hold_seconds < 900:
            points = 1.0
        else:
            points = 0.0
        if points:
            penalty_points += points
            penalties.append(f"tempo médio de posição muito curto (-{points:.1f})")

    score = round(_clamp(sum(components.values()) - penalty_points, 0, 100), 1)
    reasons = [
        f"ativa: {m7.total_trade} trades em 7d",
        f"amostra: {m30.total_trade} trades e {m30.unique_tokens} tokens em 30d",
        f"win rate: {m30.win_rate_pct:.1f}% em {m30.realized_outcomes} resultados",
        f"ROI realizado 30d: {m30.roi_pct:+.1f}%",
        f"PnL positivo em {positive_periods}/3 períodos",
    ]
    if signals is not None:
        reasons.extend(
            [
                f"dias positivos: {signals.profitable_days_30d}/{signals.trading_days_30d}",
                f"drawdown realizado estimado: {signals.realized_drawdown_pct:.1f}% do capital investido",
                f"maior dia vencedor: {signals.top_positive_day_share_pct:.1f}% dos ganhos diários",
            ]
        )
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
        signals=signals,
        source=candidate.source,
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
