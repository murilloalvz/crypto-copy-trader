import argparse
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from evaluate import main as evaluate_main
from radar import main as radar_main
from src.database import initialize_database
from src.exit_engine import ensure_exit_experiment
from src.prices import GECKOTERMINAL_MIN_INTERVAL_SECONDS
from src.wave_paper import update_wave_paper_prices


@dataclass(frozen=True)
class HybridMonitorSummary:
    discovery_runs: int
    successful_discoveries: int
    failed_discoveries: int
    settlement_runs: int
    completed_checks: int
    failed_checks: int
    configuration_error: bool = False


def _next_after(previous: float, interval: float, now: float) -> float:
    while previous <= now:
        previous += interval
    return previous


def run_hybrid_monitor(
    *,
    duration_seconds: float,
    price_interval_seconds: float,
    discovery_interval_seconds: float,
    radar_args: list[str],
    radar_runner: Callable[[list[str]], int] = radar_main,
    price_updater: Callable[[], dict[str, int]] = update_wave_paper_prices,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> HybridMonitorSummary:
    started_at = clock()
    ends_at = started_at + duration_seconds
    next_discovery = started_at
    next_settlement = started_at
    discovery_runs = successful = discovery_failures = 0
    settlement_runs = completed_checks = failed_checks = 0
    configuration_error = False

    def settle_prices() -> None:
        nonlocal settlement_runs, completed_checks, failed_checks
        result = price_updater()
        settlement_runs += 1
        completed_checks += result["completed"]
        failed_checks += result["failed"]
        print(
            "[preços] "
            f"{result['completed']} concluídos | {result['pending']} pendentes | "
            f"{result['failed']} falhos"
        )
        if "exit_open_positions" in result:
            open_signals = result.get("exit_open_signals", 0)
            estimated_seconds = open_signals * GECKOTERMINAL_MIN_INTERVAL_SECONDS
            load_pct = estimated_seconds / price_interval_seconds * 100
            print(
                "[exit-engine-v1] "
                f"{result['exit_closed_positions']} fechadas | "
                f"{result['exit_open_positions']} abertas | "
                f"{open_signals} sinais | "
                f"{result['exit_price_failures']} falhas de preço"
            )
            print(
                "[exit-polling] "
                f"carga dinâmica estimada {estimated_seconds:.1f}s/"
                f"{price_interval_seconds:.0f}s ({load_pct:.1f}%)"
            )
            if load_pct >= 80:
                print(
                    "[exit-polling] ALERTA: carga próxima da capacidade; "
                    "observe atrasos, HTTP 429 e falhas antes de manter 1m."
                )

    while clock() < ends_at:
        now = clock()
        discovery_due = now >= next_discovery
        settlement_due = now >= next_settlement

        if discovery_due:
            timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
            print()
            print(f"========== DISCOVERY | {timestamp} ==========")
            exit_code = radar_runner(radar_args)
            discovery_runs += 1
            if exit_code == 0:
                successful += 1
            else:
                discovery_failures += 1
                print(
                    f"Discovery falhou (código {exit_code}); banco anterior preservado."
                )
            now = clock()
            next_discovery = _next_after(
                next_discovery, discovery_interval_seconds, now
            )
            if exit_code == 2:
                configuration_error = True
                print("Monitor interrompido por erro de configuração.")
                break
            if exit_code == 0:
                # radar.py already settles due checkpoints after a successful search.
                next_settlement = _next_after(
                    next_settlement, price_interval_seconds, now
                )
            elif settlement_due:
                settle_prices()
                next_settlement = _next_after(
                    next_settlement, price_interval_seconds, clock()
                )
            continue

        if settlement_due:
            timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
            print()
            print(f"========== ATUALIZAÇÃO DE PREÇOS | {timestamp} ==========")
            settle_prices()
            next_settlement = _next_after(
                next_settlement, price_interval_seconds, clock()
            )
            continue

        next_event = min(next_discovery, next_settlement, ends_at)
        wait_seconds = max(0.0, next_event - clock())
        if wait_seconds > 0:
            print(
                f"Próxima tarefa em {wait_seconds / 60:.1f} min. "
                "Ctrl+C encerra com segurança."
            )
            sleeper(wait_seconds)

    return HybridMonitorSummary(
        discovery_runs=discovery_runs,
        successful_discoveries=successful,
        failed_discoveries=discovery_failures,
        settlement_runs=settlement_runs,
        completed_checks=completed_checks,
        failed_checks=failed_checks,
        configuration_error=configuration_error,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Monitora ondas em modo paper, atualizando preços mais vezes que o discovery."
        )
    )
    parser.add_argument("--hours", type=float, default=12)
    parser.add_argument("--price-interval-minutes", type=float, default=1)
    parser.add_argument("--discovery-interval-minutes", type=float, default=30)
    parser.add_argument("--tokens", type=int, default=25)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--min-liquidity", type=float, default=50_000)
    parser.add_argument("--min-volume-5m", type=float, default=5_000)
    parser.add_argument("--min-acceleration", type=float, default=1.2)
    parser.add_argument("--min-wave-score", type=float, default=55)
    parser.add_argument(
        "--skip-final-evaluation",
        action="store_true",
        help="Não gera o relatório estatístico ao terminar o monitor.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0.5 <= args.hours <= 72:
        print("Erro: --hours precisa ficar entre 0.5 e 72.", file=sys.stderr)
        return 2
    if not 1 <= args.price_interval_minutes <= 60:
        print(
            "Erro: --price-interval-minutes precisa ficar entre 1 e 60.",
            file=sys.stderr,
        )
        return 2
    if not 5 <= args.discovery_interval_minutes <= 360:
        print(
            "Erro: --discovery-interval-minutes precisa ficar entre 5 e 360.",
            file=sys.stderr,
        )
        return 2
    if args.discovery_interval_minutes < args.price_interval_minutes:
        print(
            "Erro: discovery não pode ser mais frequente que a atualização de preços.",
            file=sys.stderr,
        )
        return 2
    if not 1 <= args.tokens <= 100 or not 1 <= args.top <= 100:
        print("Erro: --tokens e --top precisam estar entre 1 e 100.", file=sys.stderr)
        return 2

    planned_discoveries = math.ceil(
        args.hours * 60 / args.discovery_interval_minutes
    )
    radar_args = [
        "--tokens",
        str(args.tokens),
        "--top",
        str(args.top),
        "--min-liquidity",
        str(args.min_liquidity),
        "--min-volume-5m",
        str(args.min_volume_5m),
        "--min-acceleration",
        str(args.min_acceleration),
        "--min-wave-score",
        str(args.min_wave_score),
    ]
    initialize_database()
    experiment = ensure_exit_experiment(
        expected_observation_interval_seconds=int(args.price_interval_minutes * 60)
    )
    print("Crypto Copy Trader — Monitor Híbrido")
    print("Modo: PAPER/READ ONLY — nenhuma compra, venda ou assinatura.")
    print(
        f"Duração: {args.hours:g}h | preços: {args.price_interval_minutes:g}min | "
        f"discovery: {args.discovery_interval_minutes:g}min"
    )
    print(f"Rodadas planejadas de discovery no Solana Tracker: {planned_discoveries}")
    print(
        "Exit engine v1 forward: "
        f"experimento {experiment['id']} | ativado em {experiment['activated_at']} | "
        f"somente sinais com ID > {experiment['start_after_signal_id']}"
    )
    try:
        summary = run_hybrid_monitor(
            duration_seconds=args.hours * 3_600,
            price_interval_seconds=args.price_interval_minutes * 60,
            discovery_interval_seconds=args.discovery_interval_minutes * 60,
            radar_args=radar_args,
        )
    except KeyboardInterrupt:
        print("\nMonitor encerrado; tudo que já foi concluído permanece no SQLite.")
        print("Execute: python evaluate.py --update-prices --cohorts")
        return 130

    print()
    print("MONITOR FINALIZADO")
    print(
        f"Discovery: {summary.successful_discoveries} sucesso(s), "
        f"{summary.failed_discoveries} falha(s) | "
        f"liquidações isoladas: {summary.settlement_runs}"
    )
    print(
        f"Checkpoints concluídos fora do discovery: {summary.completed_checks} | "
        f"falhos: {summary.failed_checks}"
    )
    if summary.configuration_error:
        print("Execute depois da correção: python evaluate.py --update-prices --cohorts")
        return 2
    if args.skip_final_evaluation:
        print("Avaliação final ignorada por --skip-final-evaluation.")
        return 0

    print()
    print("========== AVALIAÇÃO FINAL ==========")
    return evaluate_main(["--update-prices", "--cohorts"])


if __name__ == "__main__":
    raise SystemExit(main())
