import argparse

from src.database import initialize_database, rows
from src.wave_metrics import build_wave_evaluation_report
from src.wave_paper import (
    WAVE_STRATEGY_VERSION,
    backfill_wave_strategy_versions,
    update_due_paper_checks,
)


def _strategy_versions(include_all: bool) -> list[str]:
    if not include_all:
        return [WAVE_STRATEGY_VERSION]
    versions = rows(
        "SELECT DISTINCT strategy_version FROM wave_signals ORDER BY strategy_version"
    )
    return [item["strategy_version"] for item in versions] or [WAVE_STRATEGY_VERSION]


def _profit_factor(value: float | None) -> str:
    if value is None:
        return "indisponível"
    if value == float("inf"):
        return "sem perdas na amostra"
    return f"{value:.2f}"


def format_evaluation_report(report, *, show_cohorts: bool = False) -> str:
    stress_by_horizon = {}
    for stress in report.slippage_stress:
        stress_by_horizon.setdefault(stress.horizon_minutes, []).append(stress)
    exposure_by_horizon = {
        exposure.horizon_minutes: exposure for exposure in report.exposures
    }
    outliers_by_horizon = {
        item.horizon_minutes: item for item in report.outlier_diagnostics
    }
    lines = [
        f"ESTRATÉGIA: {report.strategy_version}",
        f"Sinais registrados: {report.signal_count}",
        (
            f"Horizontes: {report.completed_check_count} concluídos | "
            f"{report.pending_check_count} pendentes | {report.failed_check_count} falhos"
        ),
    ]
    if not report.horizons:
        lines.extend(
            [
                "Resultado: INCONCLUSIVO — nenhum horizonte concluído.",
                "Rode o radar novamente depois dos prazos para atualizar os preços.",
            ]
        )
        return "\n".join(lines)

    for metrics in report.horizons:
        lines.extend(
            [
                "",
                f"HORIZONTE {metrics.horizon_minutes} MINUTOS",
                f"Amostra: {metrics.sample_size} | {metrics.evidence_label}",
                (
                    f"Win rate: {metrics.win_rate_pct:.1f}% "
                    f"(intervalo 95%: {metrics.win_rate_low_pct:.1f}%–"
                    f"{metrics.win_rate_high_pct:.1f}%)"
                ),
                (
                    f"Retorno líquido médio/mediano: {metrics.average_return_pct:+.2f}% / "
                    f"{metrics.median_return_pct:+.2f}%"
                ),
                (
                    f"P&L paper total/médio: US$ {metrics.total_pnl_usd:+.2f} / "
                    f"US$ {metrics.average_pnl_usd:+.2f}"
                ),
                f"Profit factor: {_profit_factor(metrics.profit_factor)}",
                f"Drawdown acumulado paper: US$ {metrics.max_drawdown_usd:.2f}",
                (
                    f"Melhor/pior retorno: {metrics.best_return_pct:+.2f}% / "
                    f"{metrics.worst_return_pct:+.2f}%"
                ),
            ]
        )
        exposure = exposure_by_horizon.get(metrics.horizon_minutes)
        if exposure:
            budget_status = (
                "EXCEDEU O SALDO" if exposure.budget_exceeded else "dentro do saldo"
            )
            lines.append(
                f"Exposição máxima: {exposure.max_concurrent_positions} posições | "
                f"US$ {exposure.max_capital_deployed_usd:.2f} de "
                f"US$ {exposure.capital_budget_usd:.2f} "
                f"({exposure.capital_utilization_pct:.1f}%) | {budget_status}"
            )
        outliers = outliers_by_horizon.get(metrics.horizon_minutes)
        if outliers:
            if outliers.mean_ci_low_pct is None:
                lines.append(
                    "Robustez contra outlier: indisponível com apenas uma observação."
                )
            else:
                lines.append(
                    "IC 95% aproximado da média: "
                    f"{outliers.mean_ci_low_pct:+.2f}% a "
                    f"{outliers.mean_ci_high_pct:+.2f}%"
                )
                lines.append(
                    "Média sem o melhor sinal: "
                    f"{outliers.average_without_best_pct:+.2f}% | "
                    "maior vencedor / lucro bruto: "
                    + (
                        f"{outliers.top_winner_profit_share_pct:.1f}%"
                        if outliers.top_winner_profit_share_pct is not None
                        else "sem vencedores"
                    )
                )
                if outliers.positive_mean_depends_on_best:
                    lines.append(
                        "ALERTA: a média positiva desaparece ao remover o melhor sinal."
                    )
        stress_rows = stress_by_horizon.get(metrics.horizon_minutes, [])
        if stress_rows:
            lines.append("Stress de slippage por lado:")
            for stress in stress_rows:
                lines.append(
                    f"- {stress.slippage_bps_per_side / 100:.2f}%: "
                    f"n={stress.sample_size} | "
                    f"média {stress.average_return_pct:+.2f}% | "
                    f"mediana {stress.median_return_pct:+.2f}% | "
                    f"win rate {stress.win_rate_pct:.1f}% | "
                    f"PF {_profit_factor(stress.profit_factor)}"
                )
    if show_cohorts and report.cohorts:
        lines.extend(
            [
                "",
                "COORTES EXPLORATÓRIAS — LIMITES FIXADOS ANTES DA AMOSTRA",
                "Não altere os filtros usando coortes com menos de 30 observações.",
            ]
        )
        last_group = None
        dimension_names = {
            "wave_score": "Wave Score",
            "volume_acceleration": "aceleração de volume",
        }
        for cohort in report.cohorts:
            group = (cohort.horizon_minutes, cohort.dimension)
            if group != last_group:
                lines.append(
                    f"{cohort.horizon_minutes}m — {dimension_names[cohort.dimension]}"
                )
                last_group = group
            lines.append(
                f"- {cohort.bucket}: n={cohort.sample_size} | "
                f"média {cohort.average_return_pct:+.2f}% | "
                f"mediana {cohort.median_return_pct:+.2f}% | "
                f"win rate {cohort.win_rate_pct:.1f}% | "
                f"PF {_profit_factor(cohort.profit_factor)}"
            )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Avalia sinais paper do Wave Radar sem executar trades."
    )
    parser.add_argument(
        "--all-strategies",
        action="store_true",
        help="Inclui versões antigas; por padrão avalia somente a regra atual.",
    )
    parser.add_argument(
        "--cohorts",
        action="store_true",
        help="Mostra faixas exploratórias fixas de score e aceleração.",
    )
    parser.add_argument(
        "--update-prices",
        action="store_true",
        help=(
            "Atualiza checkpoints vencidos via GeckoTerminal sem consultar o "
            "Solana Tracker."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    initialize_database()
    backfill_wave_strategy_versions()
    print("Crypto Copy Trader — Wave Evaluation")
    print("Modo: PAPER/READ ONLY — resultados observados não garantem lucro futuro.")
    if args.update_prices:
        price_update = update_due_paper_checks()
        print(
            "Atualização de preços: "
            f"{price_update['completed']} concluídos | "
            f"{price_update['pending']} pendentes | "
            f"{price_update['failed']} falhos"
        )
        print("Fonte desta atualização: GeckoTerminal; Solana Tracker não consultado.")
    for version in _strategy_versions(args.all_strategies):
        print()
        print(
            format_evaluation_report(
                build_wave_evaluation_report(version), show_cohorts=args.cohorts
            )
        )
    print()
    print("Critério: menos de 30 observações é sempre inconclusivo; 100 ainda não é garantia.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
