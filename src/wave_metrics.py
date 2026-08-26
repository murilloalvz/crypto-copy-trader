import math
import statistics
from dataclasses import dataclass

from src.database import rows
from src.wave_paper import WAVE_STRATEGY_VERSION, backfill_wave_strategy_versions


SLIPPAGE_STRESS_BPS = (50, 100, 200, 300)


@dataclass(frozen=True)
class WaveHorizonMetrics:
    strategy_version: str
    horizon_minutes: int
    sample_size: int
    wins: int
    win_rate_pct: float
    win_rate_low_pct: float
    win_rate_high_pct: float
    average_return_pct: float
    median_return_pct: float
    total_pnl_usd: float
    average_pnl_usd: float
    profit_factor: float | None
    max_drawdown_usd: float
    best_return_pct: float
    worst_return_pct: float

    @property
    def evidence_label(self) -> str:
        if self.sample_size < 30:
            return "INCONCLUSIVA — menos de 30 observações"
        if self.sample_size < 100:
            return "PRELIMINAR — precisa chegar a 100 observações"
        return "EM VALIDAÇÃO — amostra maior, ainda sem garantia de lucro"


@dataclass(frozen=True)
class SlippageStressMetrics:
    horizon_minutes: int
    slippage_bps_per_side: int
    sample_size: int
    win_rate_pct: float
    average_return_pct: float
    median_return_pct: float
    total_pnl_usd: float
    profit_factor: float


@dataclass(frozen=True)
class WaveEvaluationReport:
    strategy_version: str
    signal_count: int
    completed_check_count: int
    pending_check_count: int
    failed_check_count: int
    horizons: tuple[WaveHorizonMetrics, ...]
    slippage_stress: tuple[SlippageStressMetrics, ...] = ()


def _wilson_interval(wins: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    proportion = wins / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total + z * z / (4 * total * total)
        )
        / denominator
    )
    return max(0.0, center - margin) * 100, min(1.0, center + margin) * 100


def summarize_horizon(
    strategy_version: str,
    horizon_minutes: int,
    observations: list[dict],
) -> WaveHorizonMetrics:
    returns = [float(item["return_pct"]) for item in observations]
    pnl_values = [float(item["pnl_usd"]) for item in observations]
    sample_size = len(returns)
    wins = sum(value > 0 for value in returns)
    low, high = _wilson_interval(wins, sample_size)
    profit_factor = _profit_factor(pnl_values)

    equity = peak = max_drawdown = 0.0
    for pnl in pnl_values:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    return WaveHorizonMetrics(
        strategy_version=strategy_version,
        horizon_minutes=horizon_minutes,
        sample_size=sample_size,
        wins=wins,
        win_rate_pct=wins / sample_size * 100,
        win_rate_low_pct=low,
        win_rate_high_pct=high,
        average_return_pct=statistics.fmean(returns),
        median_return_pct=statistics.median(returns),
        total_pnl_usd=sum(pnl_values),
        average_pnl_usd=statistics.fmean(pnl_values),
        profit_factor=profit_factor,
        max_drawdown_usd=max_drawdown,
        best_return_pct=max(returns),
        worst_return_pct=min(returns),
    )


def _profit_factor(pnl_values: list[float]) -> float:
    gross_profit = sum(value for value in pnl_values if value > 0)
    gross_loss = abs(sum(value for value in pnl_values if value < 0))
    return (
        gross_profit / gross_loss
        if gross_loss > 0
        else math.inf if gross_profit > 0 else 0.0
    )


def summarize_slippage_stress(
    horizon_minutes: int,
    slippage_bps_per_side: int,
    observations: list[dict],
) -> SlippageStressMetrics:
    slippage = slippage_bps_per_side / 10_000
    returns = [
        (
            float(item["market_price_usd"])
            * (1 - slippage)
            / (float(item["entry_market_price_usd"]) * (1 + slippage))
            - 1
        )
        * 100
        for item in observations
    ]
    pnl_values = [
        float(item["copy_size_usd"]) * return_pct / 100
        for item, return_pct in zip(observations, returns, strict=True)
    ]
    return SlippageStressMetrics(
        horizon_minutes=horizon_minutes,
        slippage_bps_per_side=slippage_bps_per_side,
        sample_size=len(returns),
        win_rate_pct=sum(value > 0 for value in returns) / len(returns) * 100,
        average_return_pct=statistics.fmean(returns),
        median_return_pct=statistics.median(returns),
        total_pnl_usd=sum(pnl_values),
        profit_factor=_profit_factor(pnl_values),
    )


def build_wave_evaluation_report(
    strategy_version: str = WAVE_STRATEGY_VERSION,
) -> WaveEvaluationReport:
    backfill_wave_strategy_versions()
    signal_count = rows(
        "SELECT COUNT(*) AS total FROM wave_signals WHERE strategy_version=?",
        (strategy_version,),
    )[0]["total"]
    status_counts = {
        item["status"]: item["total"]
        for item in rows(
            """SELECT c.status, COUNT(*) AS total
            FROM wave_signal_checks c
            JOIN wave_signals s ON s.id=c.signal_id
            WHERE s.strategy_version=? GROUP BY c.status""",
            (strategy_version,),
        )
    }
    completed = rows(
        """SELECT c.horizon_minutes, c.return_pct, c.pnl_usd,
        c.market_price_usd, s.entry_market_price_usd, s.copy_size_usd,
        COALESCE(c.observed_at, c.target_at) AS event_at, c.id
        FROM wave_signal_checks c
        JOIN wave_signals s ON s.id=c.signal_id
        WHERE s.strategy_version=? AND c.status='completed'
        ORDER BY c.horizon_minutes, event_at, c.id""",
        (strategy_version,),
    )
    by_horizon: dict[int, list[dict]] = {}
    for item in completed:
        by_horizon.setdefault(item["horizon_minutes"], []).append(item)
    horizons = tuple(
        summarize_horizon(strategy_version, horizon, observations)
        for horizon, observations in sorted(by_horizon.items())
    )
    slippage_stress_items = []
    for horizon, observations in sorted(by_horizon.items()):
        valid_observations = [
            item
            for item in observations
            if (item.get("market_price_usd") or 0) > 0
            and (item.get("entry_market_price_usd") or 0) > 0
            and (item.get("copy_size_usd") or 0) > 0
        ]
        for slippage_bps in SLIPPAGE_STRESS_BPS:
            if valid_observations:
                slippage_stress_items.append(
                    summarize_slippage_stress(
                        horizon, slippage_bps, valid_observations
                    )
                )
    slippage_stress = tuple(slippage_stress_items)
    return WaveEvaluationReport(
        strategy_version=strategy_version,
        signal_count=signal_count,
        completed_check_count=status_counts.get("completed", 0),
        pending_check_count=status_counts.get("pending", 0),
        failed_check_count=status_counts.get("failed", 0),
        horizons=horizons,
        slippage_stress=slippage_stress,
    )
