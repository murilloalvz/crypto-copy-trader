import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from evaluate import main as evaluate_main
from src.database import initialize_database
from src.exit_engine import ensure_exit_experiment
from src.wave_paper import update_wave_paper_prices


@dataclass(frozen=True)
class PriceOnlyMonitorSummary:
    settlement_runs: int
    completed_checks: int
    failed_checks: int


def _next_after(previous: float, interval: float, now: float) -> float:
    while previous <= now:
        previous += interval
    return previous


def run_price_only_monitor(
    *,
    duration_seconds: float,
    price_interval_seconds: float,
    price_updater: Callable[[], dict[str, int]] = update_wave_paper_prices,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> PriceOnlyMonitorSummary:
    """Keep existing paper/exit positions updated without running discovery.

    This mode exists for periods where the discovery data provider is unavailable or has no
    remaining credits. It deliberately cannot create new radar signals.
    """
    started_at = clock()
    ends_at = started_at + duration_seconds
    next_settlement = started_at
    settlement_runs = completed_checks = failed_checks = 0

    while clock() < ends_at:
        now = clock()
        if now >= next_settlement:
            timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
            print()
            print(f"========== ATUALIZAÇÃO DE PREÇOS | {timestamp} ==========")
            cycle_started = clock()
            result = price_updater()
            cycle_seconds = max(0.0, clock() - cycle_started)
            settlement_runs += 1
            completed_checks += result["completed"]
            failed_checks += result["failed"]
            print(
                "[preços] "
                f"{result['completed']} concluídos | {result['pending']} pendentes | "
                f"{result['failed']} falhos | ciclo {cycle_seconds:.1f}s"
            )
            if "exit_open_positions" in result:
                print(
                    "[exit-engine-v1] "
                    f"{result['exit_closed_positions']} fechadas | "
                    f"{result['exit_open_positions']} abertas | "
                    f"{result.get('exit_open_signals', 0)} sinais | "
                    f"{result['exit_price_failures']} falhas de preço"
                )
            next_settlement = _next_after(
                next_settlement, price_interval_seconds, clock()
            )
            continue

        wait_seconds = max(0.0, min(next_settlement, ends_at) - clock())
        if wait_seconds > 0:
            print(
                f"Próxima atualização em {wait_seconds / 60:.1f} min. "
                "Ctrl+C encerra com segurança."
            )
            sleeper(wait_seconds)

    return PriceOnlyMonitorSummary(
        settlement_runs=settlement_runs,
        completed_checks=completed_checks,
        failed_checks=failed_checks,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Mantém preços e exit engine de sinais já existentes sem executar discovery. "
            "Útil quando a Solana Tracker Data API está indisponível ou sem créditos."
        )
    )
    parser.add_argument("--hours", type=float, default=5)
    parser.add_argument("--price-interval-minutes", type=float, default=1)
    parser.add_argument(
        "--skip-final-evaluation",
        action="store_true",
        help="não executa evaluate.py ao terminar",
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

    initialize_database()
    experiment = ensure_exit_experiment(
        expected_observation_interval_seconds=int(args.price_interval_minutes * 60)
    )
    print("Crypto Copy Trader — Monitor Price-Only")
    print("Modo: PAPER/READ ONLY — discovery DESATIVADO; nenhuma ordem real.")
    print(
        f"Duração: {args.hours:g}h | preços: {args.price_interval_minutes:g}min | "
        "novos sinais: 0"
    )
    print(
        "Exit engine v1 forward: "
        f"experimento {experiment['id']} | ativado em {experiment['activated_at']} | "
        f"somente sinais com ID > {experiment['start_after_signal_id']}"
    )

    try:
        summary = run_price_only_monitor(
            duration_seconds=args.hours * 3_600,
            price_interval_seconds=args.price_interval_minutes * 60,
        )
    except KeyboardInterrupt:
        print("\nMonitor encerrado; tudo que já foi concluído permanece no SQLite.")
        return 130

    print()
    print("MONITOR PRICE-ONLY FINALIZADO")
    print(
        f"Liquidações isoladas: {summary.settlement_runs} | "
        f"checkpoints concluídos: {summary.completed_checks} | falhos: {summary.failed_checks}"
    )

    if args.skip_final_evaluation:
        return 0
    return evaluate_main(["--update-prices", "--cohorts"])


if __name__ == "__main__":
    raise SystemExit(main())
