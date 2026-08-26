import argparse
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from radar import main as radar_main
from src.database import initialize_database
from src.wave_paper import update_due_paper_checks


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
    price_updater: Callable[[], dict[str, int]] = update_due_paper_checks,
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
    parser.add_argument("--price-interval-minutes", type=float, default=5)
    parser.add_argument("--discovery-interval-minutes", type=float, default=30)
    parser.add_argument("--tokens", type=int, default=25)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--min-liquidity", type=float, default=50_000)
    parser.add_argument("--min-volume-5m", type=float, default=5_000)
    parser.add_argument("--min-acceleration", type=float, default=1.2)
    parser.add_argument("--min-wave-score", type=float, default=55)
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
    print("Crypto Copy Trader — Monitor Híbrido")
    print("Modo: PAPER/READ ONLY — nenhuma compra, venda ou assinatura.")
    print(
        f"Duração: {args.hours:g}h | preços: {args.price_interval_minutes:g}min | "
        f"discovery: {args.discovery_interval_minutes:g}min"
    )
    print(f"Máximo planejado de buscas no Solana Tracker: {planned_discoveries}")
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
    print("Execute: python evaluate.py --update-prices --cohorts")
    return 2 if summary.configuration_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
