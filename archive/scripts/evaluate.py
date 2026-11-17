import argparse

from src.database import initialize_database, rows
from src.wave_metrics import build_wave_evaluation_report
from src.wave_paper import (
    WAVE_STRATEGY_VERSION,
    backfill_wave_strategy_versions,
    update_wave_paper_prices as update_due_paper_checks,
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
    coverage_by_horizon = {
        item.horizon_minutes: item for item in report.coverages
    }
    missing_stress_by_horizon = {}
    for item in report.missing_outcome_stress:
        missing_stress_by_horizon.setdefault(item.horizon_minutes, []).append(item)
    failure_reasons_by_horizon = {}
    for item in report.failure_reasons:
        failure_reasons_by_horizon.setdefault(item.horizon_minutes, []).append(item)
    price_trace_by_horizon = {
        item.horizon_minutes: item for item in report.price_traces
    }
    lines = [
        f"ESTRATÉGIA: {report.strategy_version}",
        f"Sinais registrados: {report.signal_count}",
        (
            f"Horizontes: {report.completed_check_count} concluídos | "
            f"{report.pending_check_count} pendentes | {report.failed_check_count} falhos"
        ),
    ]
    if report.input_integrity:
        integrity = report.input_integrity
        lines.append(
            "Integridade das entradas: "
            f"{integrity.parsed_snapshot_count}/{integrity.signal_count} snapshots legíveis | "
            f"{integrity.missing_source_pool_count} sem pool de origem | "
            f"{integrity.inconsistent_volume_window_count} com janelas de volume inconsistentes"
        )
        if integrity.inconsistent_volume_window_count:
            lines.append(
                "ALERTA DE ENTRADA: volume 5m/1h/24h não foi monotônico em parte "
                "da amostra; a aceleração dessas linhas precisa ser auditada na fonte."
            )
    if not report.horizons:
        lines.extend(
            [
                "Resultado: INCONCLUSIVO — nenhum horizonte concluído.",
                "Rode o radar novamente depois dos prazos para atualizar os preços.",
            ]
        )
        return "\n".join(lines)

    for metrics in report.horizons:
        coverage = coverage_by_horizon.get(metrics.horizon_minutes)
        lines.extend(
            [
                "",
                f"HORIZONTE {metrics.horizon_minutes} MINUTOS",
            ]
        )
        if coverage:
            lines.append(
                f"Cobertura: {coverage.completed_count}/{coverage.total_count} "
                f"({coverage.coverage_pct:.1f}%) | falhos {coverage.failed_count} "
                f"({coverage.failure_pct:.1f}%) | pendentes {coverage.pending_count} "
                f"({coverage.pending_pct:.1f}%)"
            )
            if coverage.failed_count and coverage.coverage_pct < 90:
                lines.append(
                    "ALERTA DE SOBREVIVÊNCIA: o resultado observado exclui muitas falhas de preço."
                )
        lines.extend(
            [
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
        trace = price_trace_by_horizon.get(metrics.horizon_minutes)
        if trace:
            lines.append(
                "Rastreio de pool entrada/saída: "
                f"{trace.comparable_pool_count} comparáveis | "
                f"{trace.matching_pool_count} iguais | "
                f"{trace.mismatched_pool_count} diferentes | "
                f"{trace.unavailable_pool_count} sem comparação"
            )
            if trace.mismatched_pool_count:
                lines.append(
                    "ATENÇÃO DE PREÇO: parte das saídas usou pool diferente do snapshot de entrada."
                )
        failure_rows = failure_reasons_by_horizon.get(metrics.horizon_minutes, [])
        if failure_rows:
            labels = {
                "distant_historical_candle": "candle histórico distante",
                "no_historical_candle": "sem candle histórico",
                "no_pool": "pool indisponível",
                "provider_http_error": "erro HTTP do provedor",
                "temporary_provider_error": "falha temporária do provedor",
                "legacy_unclassified": "falha antiga não classificada",
                "unknown": "motivo desconhecido",
            }
            lines.append(
                "Motivos das falhas: "
                + "; ".join(
                    f"{labels.get(item.error_code, item.error_code)}: {item.count}"
                    for item in failure_rows
                )
            )
        missing_rows = missing_stress_by_horizon.get(metrics.horizon_minutes, [])
        if missing_rows and any(item.missing_count for item in missing_rows):
            lines.append(
                "Stress dos resultados sem preço (falhos + pendentes, mesma hipótese):"
            )
            for item in missing_rows:
                lines.append(
                    f"- assumindo {item.assumed_missing_return_pct:+.0f}%: "
                    f"n total={item.total_count} | média {item.average_return_pct:+.2f}% | "
                    f"P&L US$ {item.total_pnl_usd:+.2f} | "
                    f"win rate {item.win_rate_pct:.1f}% | "
                    f"PF {_profit_factor(item.profit_factor)}"
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
        if "exit_open_positions" in price_update:
            print(
                "Exit engine v1: "
                f"{price_update['exit_closed_positions']} fechadas | "
                f"{price_update['exit_open_positions']} abertas | "
                f"{price_update['exit_price_failures']} falhas de observação"
            )
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
