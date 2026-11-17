import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from radar import main as radar_main


@dataclass(frozen=True)
class CollectionSummary:
    requested_cycles: int
    completed_cycles: int
    successful_cycles: int
    failed_cycles: int
    configuration_error: bool = False


def run_collection(
    *,
    cycles: int,
    interval_seconds: float,
    radar_args: list[str],
    radar_runner: Callable[[list[str]], int] = radar_main,
    sleeper: Callable[[float], None] = time.sleep,
) -> CollectionSummary:
    successful = failed = 0
    configuration_error = False
    completed = 0
    for cycle in range(1, cycles + 1):
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        print()
        print(f"========== CICLO {cycle}/{cycles} | {timestamp} ==========")
        exit_code = radar_runner(radar_args)
        completed += 1
        if exit_code == 0:
            successful += 1
        else:
            failed += 1
            print(f"Ciclo {cycle} falhou (código {exit_code}); dados anteriores preservados.")
        if exit_code == 2:
            configuration_error = True
            print("Coleta interrompida: corrija a configuração antes de tentar novamente.")
            break
        if cycle < cycles:
            print(f"Próxima rodada em {interval_seconds / 60:g} minuto(s). Ctrl+C encerra.")
            sleeper(interval_seconds)
    return CollectionSummary(
        requested_cycles=cycles,
        completed_cycles=completed,
        successful_cycles=successful,
        failed_cycles=failed,
        configuration_error=configuration_error,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Executa ciclos limitados do Wave Radar para formar amostra paper."
    )
    parser.add_argument("--cycles", type=int, default=12)
    parser.add_argument("--interval-minutes", type=float, default=5)
    parser.add_argument("--tokens", type=int, default=25)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--min-liquidity", type=float, default=50_000)
    parser.add_argument("--min-volume-5m", type=float, default=5_000)
    parser.add_argument("--min-acceleration", type=float, default=1.2)
    parser.add_argument("--min-wave-score", type=float, default=55)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.cycles <= 288 or not 0.5 <= args.interval_minutes <= 60:
        print(
            "Erro: --cycles deve ficar entre 1 e 288 e --interval-minutes entre 0.5 e 60.",
            file=sys.stderr,
        )
        return 2
    if not 1 <= args.tokens <= 100 or not 1 <= args.top <= 100:
        print("Erro: --tokens e --top precisam estar entre 1 e 100.", file=sys.stderr)
        return 2

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
    print("Crypto Copy Trader — Coletor do Wave Radar")
    print("Modo: PAPER/READ ONLY. Pode encerrar com Ctrl+C sem perder rodadas salvas.")
    try:
        summary = run_collection(
            cycles=args.cycles,
            interval_seconds=args.interval_minutes * 60,
            radar_args=radar_args,
        )
    except KeyboardInterrupt:
        print("\nColeta encerrada pelo usuário; sinais já concluídos continuam no banco.")
        print("Execute: python evaluate.py")
        return 130

    print()
    print("COLETA FINALIZADA")
    print(
        f"Ciclos concluídos: {summary.completed_cycles}/{summary.requested_cycles} | "
        f"sucesso: {summary.successful_cycles} | falhas: {summary.failed_cycles}"
    )
    print("Agora execute: python evaluate.py")
    return 2 if summary.configuration_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
