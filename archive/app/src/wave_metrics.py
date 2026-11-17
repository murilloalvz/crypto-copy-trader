import json
import math
import statistics
from dataclasses import dataclass

from src.config import settings
from src.database import connection, rows
from src.wave_paper import WAVE_STRATEGY_VERSION, backfill_wave_strategy_versions


SLIPPAGE_STRESS_BPS = (50, 100, 200, 300)
MISSING_OUTCOME_STRESS_PCT = (0.0, -25.0, -50.0, -100.0)
T_CRITICAL_95 = (
    12.706,
    4.303,
    3.182,
    2.776,
    2.571,
    2.447,
    2.365,
    2.306,
    2.262,
    2.228,
    2.201,
    2.179,
    2.160,
    2.145,
    2.131,
    2.120,
    2.110,
    2.101,
    2.093,
    2.086,
    2.080,
    2.074,
    2.069,
    2.064,
    2.060,
    2.056,
    2.052,
    2.048,
    2.045,
    2.042,
)


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
class WaveCohortMetrics:
    horizon_minutes: int
    dimension: str
    bucket: str
    sample_size: int
    win_rate_pct: float
    average_return_pct: float
    median_return_pct: float
    profit_factor: float


@dataclass(frozen=True)
class WaveExposureMetrics:
    horizon_minutes: int
    max_concurrent_positions: int
    max_capital_deployed_usd: float
    capital_budget_usd: float
    capital_utilization_pct: float
    budget_exceeded: bool


@dataclass(frozen=True)
class WaveOutlierMetrics:
    horizon_minutes: int
    sample_size: int
    return_stddev_pct: float | None
    mean_ci_low_pct: float | None
    mean_ci_high_pct: float | None
    average_without_best_pct: float | None
    top_winner_profit_share_pct: float | None
    positive_mean_depends_on_best: bool


@dataclass(frozen=True)
class WaveCoverageMetrics:
    horizon_minutes: int
    total_count: int
    completed_count: int
    failed_count: int
    pending_count: int
    coverage_pct: float
    failure_pct: float
    pending_pct: float


@dataclass(frozen=True)
class WaveMissingOutcomeStressMetrics:
    horizon_minutes: int
    assumed_missing_return_pct: float
    completed_count: int
    missing_count: int
    total_count: int
    win_rate_pct: float
    average_return_pct: float
    total_pnl_usd: float
    profit_factor: float


@dataclass(frozen=True)
class WaveFailureReasonMetrics:
    horizon_minutes: int
    error_code: str
    count: int


@dataclass(frozen=True)
class WavePriceTraceMetrics:
    horizon_minutes: int
    completed_count: int
    comparable_pool_count: int
    matching_pool_count: int
    mismatched_pool_count: int
    unavailable_pool_count: int


@dataclass(frozen=True)
class WaveInputIntegrityMetrics:
    signal_count: int
    parsed_snapshot_count: int
    missing_source_pool_count: int
    inconsistent_volume_window_count: int


@dataclass(frozen=True)
class WaveEvaluationReport:
    strategy_version: str
    signal_count: int
    completed_check_count: int
    pending_check_count: int
    failed_check_count: int
    horizons: tuple[WaveHorizonMetrics, ...]
    slippage_stress: tuple[SlippageStressMetrics, ...] = ()
    cohorts: tuple[WaveCohortMetrics, ...] = ()
    exposures: tuple[WaveExposureMetrics, ...] = ()
    outlier_diagnostics: tuple[WaveOutlierMetrics, ...] = ()
    coverages: tuple[WaveCoverageMetrics, ...] = ()
    missing_outcome_stress: tuple[WaveMissingOutcomeStressMetrics, ...] = ()
    failure_reasons: tuple[WaveFailureReasonMetrics, ...] = ()
    price_traces: tuple[WavePriceTraceMetrics, ...] = ()
    input_integrity: WaveInputIntegrityMetrics | None = None


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


def backfill_wave_check_error_codes() -> int:
    """Classify legacy paper failures without deleting their original messages."""
    failed = rows(
        """SELECT id, error FROM wave_signal_checks
        WHERE status='failed' AND error_code IS NULL"""
    )
    updates = []
    for item in failed:
        message = str(item.get("error") or "").lower()
        if "distante demais" in message:
            code = "distant_historical_candle"
        elif "sem candle histórico" in message:
            code = "no_historical_candle"
        elif "nenhum pool encontrado" in message:
            code = "no_pool"
        elif "geckoterminal recusou" in message:
            code = "provider_http_error"
        elif "temporariamente indisponível" in message:
            code = "temporary_provider_error"
        else:
            code = "legacy_unclassified"
        updates.append((code, item["id"]))
    if updates:
        with connection() as conn:
            conn.executemany(
                "UPDATE wave_signal_checks SET error_code=? WHERE id=?",
                updates,
            )
    return len(updates)


def summarize_coverage(
    horizon_minutes: int,
    checks: list[dict],
) -> WaveCoverageMetrics:
    total = len(checks)
    completed = sum(item["status"] == "completed" for item in checks)
    failed = sum(item["status"] == "failed" for item in checks)
    pending = sum(item["status"] == "pending" for item in checks)
    denominator = total or 1
    return WaveCoverageMetrics(
        horizon_minutes=horizon_minutes,
        total_count=total,
        completed_count=completed,
        failed_count=failed,
        pending_count=pending,
        coverage_pct=completed / denominator * 100,
        failure_pct=failed / denominator * 100,
        pending_pct=pending / denominator * 100,
    )


def summarize_missing_outcome_stress(
    horizon_minutes: int,
    assumed_missing_return_pct: float,
    checks: list[dict],
) -> WaveMissingOutcomeStressMetrics:
    completed = [item for item in checks if item["status"] == "completed"]
    missing = [item for item in checks if item["status"] != "completed"]
    returns = [float(item["return_pct"]) for item in completed]
    pnl_values = [float(item["pnl_usd"]) for item in completed]
    for item in missing:
        assumed_pnl = (
            float(item["copy_size_usd"]) * assumed_missing_return_pct / 100
        )
        returns.append(assumed_missing_return_pct)
        pnl_values.append(assumed_pnl)
    total = len(returns)
    return WaveMissingOutcomeStressMetrics(
        horizon_minutes=horizon_minutes,
        assumed_missing_return_pct=assumed_missing_return_pct,
        completed_count=len(completed),
        missing_count=len(missing),
        total_count=total,
        win_rate_pct=(sum(value > 0 for value in returns) / total * 100 if total else 0),
        average_return_pct=statistics.fmean(returns) if returns else 0,
        total_pnl_usd=sum(pnl_values),
        profit_factor=_profit_factor(pnl_values),
    )


def summarize_price_trace(
    horizon_minutes: int,
    completed_checks: list[dict],
) -> WavePriceTraceMetrics:
    matching = mismatched = unavailable = 0
    for item in completed_checks:
        source_pool = None
        try:
            source_pool = json.loads(item["snapshot_json"])["token"].get(
                "pool_address"
            )
        except (KeyError, TypeError, json.JSONDecodeError):
            pass
        exit_pool = item.get("exit_pool_address")
        if not source_pool or not exit_pool:
            unavailable += 1
        elif str(source_pool).strip().lower() == str(exit_pool).strip().lower():
            matching += 1
        else:
            mismatched += 1
    return WavePriceTraceMetrics(
        horizon_minutes=horizon_minutes,
        completed_count=len(completed_checks),
        comparable_pool_count=matching + mismatched,
        matching_pool_count=matching,
        mismatched_pool_count=mismatched,
        unavailable_pool_count=unavailable,
    )


def summarize_input_integrity(signals: list[dict]) -> WaveInputIntegrityMetrics:
    parsed = missing_pool = inconsistent_volume = 0
    for signal in signals:
        try:
            token = json.loads(signal["snapshot_json"])["token"]
            volume_5m = float(token.get("volume_5m_usd") or 0)
            volume_1h = float(token.get("volume_1h_usd") or 0)
            volume_24h = float(token.get("volume_24h_usd") or 0)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        parsed += 1
        if not token.get("pool_address"):
            missing_pool += 1
        if volume_5m > volume_1h or volume_1h > volume_24h:
            inconsistent_volume += 1
    return WaveInputIntegrityMetrics(
        signal_count=len(signals),
        parsed_snapshot_count=parsed,
        missing_source_pool_count=missing_pool,
        inconsistent_volume_window_count=inconsistent_volume,
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


def _score_bucket(value: float) -> str:
    if value < 55:
        return "<55"
    if value < 65:
        return "55–64.9"
    if value < 75:
        return "65–74.9"
    return "75+"


def _volume_acceleration(snapshot_json: str) -> float | None:
    try:
        token = json.loads(snapshot_json)["token"]
        volume_5m = float(token.get("volume_5m_usd") or 0)
        volume_1h = float(token.get("volume_1h_usd") or 0)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    five_minute_average = volume_1h / 12
    return volume_5m / five_minute_average if five_minute_average > 0 else None


def _acceleration_bucket(value: float | None) -> str:
    if value is None:
        return "indisponível"
    if value < 1.2:
        return "<1.20x"
    if value < 1.5:
        return "1.20–1.49x"
    if value < 2:
        return "1.50–1.99x"
    return "2.00x+"


def summarize_fixed_cohorts(
    horizon_minutes: int,
    observations: list[dict],
) -> tuple[WaveCohortMetrics, ...]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for item in observations:
        buckets = (
            ("wave_score", _score_bucket(float(item["wave_score"]))),
            (
                "volume_acceleration",
                _acceleration_bucket(_volume_acceleration(item["snapshot_json"])),
            ),
        )
        for key in buckets:
            grouped.setdefault(key, []).append(item)

    dimension_order = {"wave_score": 0, "volume_acceleration": 1}
    bucket_order = {
        "<55": 0,
        "55–64.9": 1,
        "65–74.9": 2,
        "75+": 3,
        "indisponível": 0,
        "<1.20x": 1,
        "1.20–1.49x": 2,
        "1.50–1.99x": 3,
        "2.00x+": 4,
    }
    results = []
    for (dimension, bucket), items in sorted(
        grouped.items(),
        key=lambda pair: (
            dimension_order[pair[0][0]],
            bucket_order[pair[0][1]],
        ),
    ):
        returns = [float(item["return_pct"]) for item in items]
        pnl_values = [float(item["pnl_usd"]) for item in items]
        results.append(
            WaveCohortMetrics(
                horizon_minutes=horizon_minutes,
                dimension=dimension,
                bucket=bucket,
                sample_size=len(items),
                win_rate_pct=sum(value > 0 for value in returns) / len(items) * 100,
                average_return_pct=statistics.fmean(returns),
                median_return_pct=statistics.median(returns),
                profit_factor=_profit_factor(pnl_values),
            )
        )
    return tuple(results)


def summarize_exposure(
    horizon_minutes: int,
    observations: list[dict],
    capital_budget_usd: float,
) -> WaveExposureMetrics:
    events = []
    for item in observations:
        amount = float(item["copy_size_usd"])
        events.append((int(item["detected_at"]), 1, amount, 1))
        events.append((int(item["target_at"]), 0, -amount, -1))
    capital = 0.0
    positions = 0
    max_capital = 0.0
    max_positions = 0
    for _timestamp, _event_order, capital_delta, position_delta in sorted(events):
        capital += capital_delta
        positions += position_delta
        max_capital = max(max_capital, capital)
        max_positions = max(max_positions, positions)
    utilization = (
        max_capital / capital_budget_usd * 100 if capital_budget_usd > 0 else math.inf
    )
    return WaveExposureMetrics(
        horizon_minutes=horizon_minutes,
        max_concurrent_positions=max_positions,
        max_capital_deployed_usd=max_capital,
        capital_budget_usd=capital_budget_usd,
        capital_utilization_pct=utilization,
        budget_exceeded=capital_budget_usd <= 0 or max_capital > capital_budget_usd,
    )


def summarize_outlier_sensitivity(
    horizon_minutes: int,
    observations: list[dict],
) -> WaveOutlierMetrics:
    returns = [float(item["return_pct"]) for item in observations]
    pnl_values = [float(item["pnl_usd"]) for item in observations]
    sample_size = len(returns)
    average = statistics.fmean(returns)
    gross_profit = sum(value for value in pnl_values if value > 0)
    largest_profit = max((value for value in pnl_values if value > 0), default=None)
    top_share = (
        largest_profit / gross_profit * 100
        if largest_profit is not None and gross_profit > 0
        else None
    )

    if sample_size < 2:
        return WaveOutlierMetrics(
            horizon_minutes=horizon_minutes,
            sample_size=sample_size,
            return_stddev_pct=None,
            mean_ci_low_pct=None,
            mean_ci_high_pct=None,
            average_without_best_pct=None,
            top_winner_profit_share_pct=top_share,
            positive_mean_depends_on_best=False,
        )

    stddev = statistics.stdev(returns)
    degrees_of_freedom = sample_size - 1
    critical = (
        T_CRITICAL_95[degrees_of_freedom - 1]
        if degrees_of_freedom <= len(T_CRITICAL_95)
        else 1.96
    )
    margin = critical * stddev / math.sqrt(sample_size)
    best_index = max(range(sample_size), key=returns.__getitem__)
    without_best = returns[:best_index] + returns[best_index + 1 :]
    average_without_best = statistics.fmean(without_best)
    return WaveOutlierMetrics(
        horizon_minutes=horizon_minutes,
        sample_size=sample_size,
        return_stddev_pct=stddev,
        mean_ci_low_pct=average - margin,
        mean_ci_high_pct=average + margin,
        average_without_best_pct=average_without_best,
        top_winner_profit_share_pct=top_share,
        positive_mean_depends_on_best=average > 0 and average_without_best <= 0,
    )


def build_wave_evaluation_report(
    strategy_version: str = WAVE_STRATEGY_VERSION,
    *,
    capital_budget_usd: float | None = None,
) -> WaveEvaluationReport:
    capital_budget = (
        settings.starting_balance_usd
        if capital_budget_usd is None
        else float(capital_budget_usd)
    )
    backfill_wave_strategy_versions()
    backfill_wave_check_error_codes()
    signals = rows(
        """SELECT id, snapshot_json FROM wave_signals
        WHERE strategy_version=? ORDER BY detected_at, id""",
        (strategy_version,),
    )
    signal_count = len(signals)
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
    all_checks = rows(
        """SELECT c.horizon_minutes, c.return_pct, c.pnl_usd, c.status,
        c.error_code,
        c.market_price_usd, s.entry_market_price_usd, s.copy_size_usd,
        s.wave_score, s.snapshot_json, s.detected_at, c.target_at,
        COALESCE(c.observed_at, c.target_at) AS event_at, c.id,
        pc.pool_address AS exit_pool_address
        FROM wave_signal_checks c
        JOIN wave_signals s ON s.id=c.signal_id
        LEFT JOIN price_cache pc ON pc.token_mint=s.token_mint
        AND pc.minute_ts=(c.target_at - (c.target_at % 60))
        WHERE s.strategy_version=?
        ORDER BY c.horizon_minutes, event_at, c.id""",
        (strategy_version,),
    )
    completed = [item for item in all_checks if item["status"] == "completed"]
    all_by_horizon: dict[int, list[dict]] = {}
    for item in all_checks:
        all_by_horizon.setdefault(item["horizon_minutes"], []).append(item)
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
    cohorts = tuple(
        cohort
        for horizon, observations in sorted(by_horizon.items())
        for cohort in summarize_fixed_cohorts(horizon, observations)
    )
    exposures = tuple(
        summarize_exposure(horizon, observations, capital_budget)
        for horizon, observations in sorted(by_horizon.items())
    )
    outlier_diagnostics = tuple(
        summarize_outlier_sensitivity(horizon, observations)
        for horizon, observations in sorted(by_horizon.items())
    )
    coverages = tuple(
        summarize_coverage(horizon, checks)
        for horizon, checks in sorted(all_by_horizon.items())
    )
    missing_outcome_stress = tuple(
        summarize_missing_outcome_stress(horizon, assumption, checks)
        for horizon, checks in sorted(all_by_horizon.items())
        for assumption in MISSING_OUTCOME_STRESS_PCT
    )
    failure_counts: dict[tuple[int, str], int] = {}
    for item in all_checks:
        if item["status"] != "failed":
            continue
        key = (
            int(item["horizon_minutes"]),
            str(item.get("error_code") or "unknown"),
        )
        failure_counts[key] = failure_counts.get(key, 0) + 1
    failure_reasons = tuple(
        WaveFailureReasonMetrics(horizon, error_code, count)
        for (horizon, error_code), count in sorted(failure_counts.items())
    )
    price_traces = tuple(
        summarize_price_trace(horizon, observations)
        for horizon, observations in sorted(by_horizon.items())
    )
    return WaveEvaluationReport(
        strategy_version=strategy_version,
        signal_count=signal_count,
        completed_check_count=status_counts.get("completed", 0),
        pending_check_count=status_counts.get("pending", 0),
        failed_check_count=status_counts.get("failed", 0),
        horizons=horizons,
        slippage_stress=slippage_stress,
        cohorts=cohorts,
        exposures=exposures,
        outlier_diagnostics=outlier_diagnostics,
        coverages=coverages,
        missing_outcome_stress=missing_outcome_stress,
        failure_reasons=failure_reasons,
        price_traces=price_traces,
        input_integrity=summarize_input_integrity(signals),
    )
