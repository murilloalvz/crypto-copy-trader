import math
import statistics
from dataclasses import dataclass

from src.database import rows


@dataclass(frozen=True)
class ExitPolicyMetrics:
    policy_version: str
    positions: int
    closed: int
    open: int
    failed: int
    coverage_pct: float
    mean_return_pct: float | None
    median_return_pct: float | None
    win_rate_pct: float | None
    profit_factor: float | None
    worst_return_pct: float | None
    best_return_pct: float | None
    p25_return_pct: float | None
    p75_return_pct: float | None
    mean_without_best_pct: float | None
    largest_winner_share_pct: float | None
    mean_mfe_pct: float | None
    mean_mae_pct: float | None
    mean_mfe_captured_pct: float | None
    mean_duration_seconds: float | None
    median_duration_seconds: float | None
    max_closed_pnl_drawdown_usd: float


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _profit_factor(values: list[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    if losses == 0:
        return math.inf if gains > 0 else 0.0
    return gains / losses


def _drawdown(pnl_values: list[float]) -> float:
    cumulative = peak = maximum = 0.0
    for pnl in pnl_values:
        cumulative += pnl
        peak = max(peak, cumulative)
        maximum = max(maximum, peak - cumulative)
    return maximum


def exit_policy_metrics(experiment_id: int) -> tuple[ExitPolicyMetrics, ...]:
    policies = rows(
        """SELECT id, policy_version FROM exit_policies
        WHERE experiment_id=? ORDER BY id""",
        (experiment_id,),
    )
    output = []
    for policy in policies:
        positions = rows(
            """SELECT * FROM exit_positions WHERE experiment_id=? AND policy_id=?
            ORDER BY COALESCE(exit_at, entry_at), signal_id""",
            (experiment_id, policy["id"]),
        )
        closed = [item for item in positions if item["status"] == "closed"]
        returns = [float(item["net_return_pct"]) for item in closed]
        winners = [value for value in returns if value > 0]
        mfe = [float(item["mfe_pct"]) for item in closed]
        mae = [float(item["mae_pct"]) for item in closed]
        captured = [
            float(item["net_return_pct"]) / float(item["mfe_pct"]) * 100
            for item in closed
            if float(item["mfe_pct"]) > 0
        ]
        durations = [float(item["duration_seconds"]) for item in closed]
        pnl = [float(item["pnl_usd"]) for item in closed]
        output.append(
            ExitPolicyMetrics(
                policy["policy_version"],
                len(positions),
                len(closed),
                sum(item["status"] == "open" for item in positions),
                sum(item["status"] == "failed" for item in positions),
                len(closed) / len(positions) * 100 if positions else 0.0,
                statistics.fmean(returns) if returns else None,
                statistics.median(returns) if returns else None,
                len(winners) / len(returns) * 100 if returns else None,
                _profit_factor(returns) if returns else None,
                min(returns) if returns else None,
                max(returns) if returns else None,
                _percentile(returns, 0.25) if returns else None,
                _percentile(returns, 0.75) if returns else None,
                statistics.fmean(sorted(returns)[:-1]) if len(returns) > 1 else None,
                max(winners) / sum(winners) * 100 if winners else None,
                statistics.fmean(mfe) if mfe else None,
                statistics.fmean(mae) if mae else None,
                statistics.fmean(captured) if captured else None,
                statistics.fmean(durations) if durations else None,
                statistics.median(durations) if durations else None,
                _drawdown(pnl),
            )
        )
    return tuple(output)


def paired_closed_signal_count(experiment_id: int) -> int:
    policy_count = rows(
        "SELECT COUNT(*) AS total FROM exit_policies WHERE experiment_id=?",
        (experiment_id,),
    )[0]["total"]
    if not policy_count:
        return 0
    return rows(
        """SELECT COUNT(*) AS total FROM (
            SELECT signal_id FROM exit_positions
            WHERE experiment_id=? AND status='closed'
            GROUP BY signal_id HAVING COUNT(*)=?
        )""",
        (experiment_id, policy_count),
    )[0]["total"]


def format_exit_evaluation(experiment_id: int) -> str:
    experiment = rows("SELECT * FROM exit_experiments WHERE id=?", (experiment_id,))
    if not experiment:
        raise ValueError(f"Experimento inexistente: {experiment_id}")
    experiment = experiment[0]
    lines = [
        "Crypto Copy Trader — Exit Engine Evaluation",
        "Modo: PAPER/READ ONLY — nenhuma política é declarada vencedora.",
        "",
        f"Engine: {experiment['engine_version']} | experimento: {experiment_id}",
        f"Entrada: {experiment['entry_strategy_version']}",
        (
            f"Coorte forward: activated_at={experiment['activated_at']} | "
            f"signal_id>{experiment['start_after_signal_id']}"
        ),
        (
            "Intervalo esperado entre observações: "
            f"{experiment['expected_observation_interval_seconds']}s"
        ),
        f"Sinais com todas as políticas fechadas: {paired_closed_signal_count(experiment_id)}",
    ]
    for metric in exit_policy_metrics(experiment_id):
        lines.extend(
            [
                "",
                metric.policy_version,
                (
                    f"Posições: {metric.positions} | fechadas {metric.closed} | "
                    f"abertas {metric.open} | falhas {metric.failed} | "
                    f"cobertura {metric.coverage_pct:.1f}%"
                ),
            ]
        )
        if metric.closed:
            pf = "sem perdas" if math.isinf(metric.profit_factor) else f"{metric.profit_factor:.2f}"
            lines.extend(
                [
                    (
                        f"Retorno médio/mediano: {metric.mean_return_pct:+.2f}% / "
                        f"{metric.median_return_pct:+.2f}% | win rate {metric.win_rate_pct:.1f}% | PF {pf}"
                    ),
                    (
                        f"P25/P75: {metric.p25_return_pct:+.2f}% / {metric.p75_return_pct:+.2f}% | "
                        f"pior/melhor {metric.worst_return_pct:+.2f}% / {metric.best_return_pct:+.2f}%"
                    ),
                    (
                        f"MFE médio {metric.mean_mfe_pct:+.2f}% | MAE médio {metric.mean_mae_pct:+.2f}% | "
                        f"drawdown fechado US$ {metric.max_closed_pnl_drawdown_usd:.2f}"
                    ),
                    (
                        f"Duração média/mediana: {metric.mean_duration_seconds / 60:.1f} / "
                        f"{metric.median_duration_seconds / 60:.1f} min"
                    ),
                ]
            )
            if metric.mean_without_best_pct is not None:
                winner_share = (
                    "sem vencedores"
                    if metric.largest_winner_share_pct is None
                    else f"{metric.largest_winner_share_pct:.1f}%"
                )
                lines.append(
                    f"Média sem o melhor trade: {metric.mean_without_best_pct:+.2f}% | "
                    f"maior vencedor/lucro bruto: {winner_share}"
                )
            if metric.mean_mfe_captured_pct is not None:
                lines.append(
                    "Percentual médio do MFE capturado nas posições com MFE positivo: "
                    f"{metric.mean_mfe_captured_pct:.1f}%"
                )
    lines.extend(
        [
            "",
            "LIMITAÇÃO DE EXECUÇÃO",
            "Thresholds reagem apenas a candles observados e concluídos.",
            "Em gaps, a saída usa o primeiro preço observado após o cruzamento, não o threshold.",
            "Intervalos não observados não são reconstruídos; intraminuto não é conhecido.",
        ]
    )
    return "\n".join(lines)
