import argparse
from datetime import datetime, timezone

from src.database import initialize_database
from src.wave_bankroll import completed_wave_returns, simulate_bankroll
from src.wave_paper import WAVE_STRATEGY_VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Simula reinvestimento sequencial usando retornos paper reais."
    )
    parser.add_argument("--starting-balance", type=float, default=100)
    parser.add_argument("--allocation-pct", type=float, default=30)
    parser.add_argument("--horizon-minutes", type=int, default=5)
    parser.add_argument("--strategy", default=WAVE_STRATEGY_VERSION)
    parser.add_argument("--expected-trades", type=int)
    return parser


def format_simulation(simulation, *, strategy: str, horizon_minutes: int) -> str:
    lines = [
        "Crypto Copy Trader — Simulação de Banca",
        "Modo: PAPER/READ ONLY — nenhuma ordem ou movimentação de dinheiro.",
        f"Estratégia: {strategy} | horizonte: {horizon_minutes}m",
        f"Trades sequenciais: {len(simulation.points)}",
        (
            f"Banca inicial: US$ {simulation.starting_balance_usd:.2f} | "
            f"alocação por entrada: {simulation.allocation_pct:.1f}%"
        ),
        f"Banca final: US$ {simulation.final_balance_usd:.2f}",
        f"Lucro total: US$ {simulation.total_profit_usd:+.2f}",
        f"Retorno acumulado: {simulation.total_return_pct:+.2f}%",
        (
            f"Maior drawdown: US$ {simulation.max_drawdown_usd:.2f} "
            f"({simulation.max_drawdown_pct:.2f}%)"
        ),
        f"Maior sequência de perdas: {simulation.max_losing_streak}",
        "",
        "EVOLUÇÃO DA BANCA",
    ]
    for point in simulation.points:
        timestamp = datetime.fromtimestamp(
            point.detected_at, tz=timezone.utc
        ).isoformat(timespec="seconds")
        lines.append(
            f"{point.trade_number:02d}. {timestamp} | {point.symbol} | "
            f"retorno {point.return_pct:+.2f}% | entrada US$ {point.stake_usd:.2f} | "
            f"P&L US$ {point.pnl_usd:+.2f} | banca US$ {point.balance_usd:.2f} | "
            f"DD {point.drawdown_pct:.2f}%"
        )
    lines.extend(
        [
            "",
            "Hipótese: os trades são encerrados e reinvestidos sequencialmente na ordem "
            "de detecção; sobreposição real de posições não é modelada nesta simulação.",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    initialize_database()
    observations = completed_wave_returns(args.strategy, args.horizon_minutes)
    if args.expected_trades is not None and len(observations) != args.expected_trades:
        raise SystemExit(
            f"Esperados {args.expected_trades} trades, mas o banco contém "
            f"{len(observations)} para esse recorte."
        )
    simulation = simulate_bankroll(
        observations,
        starting_balance_usd=args.starting_balance,
        allocation_pct=args.allocation_pct,
    )
    print(
        format_simulation(
            simulation,
            strategy=args.strategy,
            horizon_minutes=args.horizon_minutes,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
