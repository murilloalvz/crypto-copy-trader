import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from src.database import initialize_database
from src.wave_bankroll import (
    completed_wave_observations,
    simulate_concurrent_bankroll,
)
from src.wave_paper import WAVE_V2_STRATEGY_VERSION


@dataclass(frozen=True)
class Scenario:
    name: str
    position_pct: float
    max_exposure_pct: float


SCENARIOS = (
    Scenario("CONSERVADOR", 10, 40),
    Scenario("MODERADO", 20, 60),
    Scenario("AGRESSIVO", 30, 60),
    Scenario("MUITO AGRESSIVO", 30, 70),
)
SCALE_BALANCES = (100.0, 500.0, 1_000.0)
EXTRA_ROUND_TRIP_COST_BPS = (0, 25, 50, 100, 200)


def _money(value: float) -> str:
    return f"US$ {value:,.2f}"


def _timestamp(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(timespec="seconds")


def _format_summary(simulation) -> list[str]:
    liquidity = (
        f"{simulation.max_entry_to_liquidity_pct:.4f}%"
        if simulation.max_entry_to_liquidity_pct is not None
        else "indisponível"
    )
    slippage = ", ".join(
        f"{value / 100:.2f}%/lado" for value in simulation.slippage_bps_values
    ) or "indisponível"
    return [
        (
            f"{simulation.scenario_name} | posição {simulation.position_pct:.0f}% | "
            f"exposição {simulation.max_exposure_pct:.0f}%"
        ),
        (
            f"Banca: {_money(simulation.starting_balance_usd)} -> "
            f"{_money(simulation.final_balance_usd)} | lucro "
            f"{_money(simulation.total_profit_usd)} | retorno "
            f"{simulation.total_return_pct:+.2f}%"
        ),
        (
            f"Executados: {simulation.executed_trade_count} | ignorados: "
            f"{simulation.skipped_trade_count} | win rate: "
            f"{simulation.win_rate_pct:.1f}% ({simulation.wins}/"
            f"{simulation.executed_trade_count})"
        ),
        (
            f"Drawdown: {_money(simulation.max_drawdown_usd)} "
            f"({simulation.max_drawdown_pct:.2f}%) | sequência de perdas: "
            f"{simulation.max_losing_streak}"
        ),
        (
            f"Posições simultâneas: {simulation.max_concurrent_positions} | "
            f"exposição máxima: {_money(simulation.max_exposure_usd)} "
            f"({simulation.max_exposure_reached_pct:.2f}%)"
        ),
        (
            f"Entrada média/máxima: {_money(simulation.average_entry_usd)} / "
            f"{_money(simulation.max_entry_usd)}"
        ),
        (
            f"Slippage observado no experimento: {slippage} | maior entrada/liquidez: "
            f"{liquidity} | liquidez ausente: {simulation.missing_liquidity_count}"
        ),
    ]


def _apply_extra_cost(observations, cost_bps):
    return tuple(
        replace(item, return_pct=item.return_pct - cost_bps / 100)
        for item in observations
    )


def format_report(simulations, scale_simulations, cost_stress_simulations=()) -> str:
    lines = [
        "Crypto Copy Trader — Backtest Concorrente",
        "Modo: PAPER/READ ONLY — nenhuma ordem ou movimentação de dinheiro.",
        "Prioridade simultânea: maior Wave Score; desempate pelo ID do sinal.",
        "Saída: target_at do checkpoint; observed_at é apenas quando o preço foi coletado.",
        "Entradas parciais usam somente o restante permitido pela exposição.",
    ]
    for simulation in simulations:
        lines.extend(["", *_format_summary(simulation), "Ignorados por falta de capital:"])
        skipped = [item for item in simulation.trades if not item.executed]
        if skipped:
            lines.extend(
                f"- {_timestamp(item.detected_at)} | {item.symbol} | "
                f"Wave {item.wave_score:.1f}"
                for item in skipped
            )
        else:
            lines.append("- nenhum")
        lines.append("Evolução da banca:")
        lines.extend(
            f"- {_timestamp(point.timestamp)} {point.event} | equity "
            f"{_money(point.equity_usd)} | caixa {_money(point.cash_usd)} | "
            f"bloqueado {_money(point.locked_usd)} | posições "
            f"{point.open_positions} | exposição {point.exposure_pct:.1f}% | "
            f"DD {point.drawdown_pct:.2f}%"
            for point in simulation.evolution
        )

    lines.extend(["", "ESCALA — TODOS OS CENÁRIOS"])
    for simulation in scale_simulations:
        lines.append(
            f"- {simulation.scenario_name} | inicial "
            f"{_money(simulation.starting_balance_usd)} | final "
            f"{_money(simulation.final_balance_usd)} | retorno "
            f"{simulation.total_return_pct:+.2f}% | DD "
            f"{simulation.max_drawdown_pct:.2f}% | executados "
            f"{simulation.executed_trade_count}"
        )
    if cost_stress_simulations:
        lines.extend(
            [
                "",
                "STRESS DE CUSTO ADICIONAL — IDA E VOLTA",
                "Sensibilidade descontada além do slippage que já está nos retornos.",
            ]
        )
        for cost_bps, simulation in cost_stress_simulations:
            lines.append(
                f"- {simulation.scenario_name} | custo extra {cost_bps} bps | "
                f"final {_money(simulation.final_balance_usd)} | retorno "
                f"{simulation.total_return_pct:+.2f}% | DD "
                f"{simulation.max_drawdown_pct:.2f}% | win rate "
                f"{simulation.win_rate_pct:.1f}%"
            )
    lines.extend(
        [
            "",
            "CUSTOS E EXECUTABILIDADE",
            "- Os retornos líquidos armazenados já aplicam o slippage configurado na entrada e saída.",
            "- Fees adicionais não são descontados porque não existem valores observados por sinal.",
            "- Entrada/liquidez é apenas proxy de impacto; sem curva/quote histórica, nenhum impacto foi inventado.",
            "- O capital fica bloqueado até target_at e nunca é reutilizado antes do fechamento.",
            "- O drawdown usa a equity contábil nos fechamentos; posições abertas não são marcadas a mercado.",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backtest concorrente dos sinais paper já registrados."
    )
    parser.add_argument("--strategy", default=WAVE_V2_STRATEGY_VERSION)
    parser.add_argument("--horizon-minutes", type=int, default=5)
    parser.add_argument("--expected-trades", type=int, default=64)
    parser.add_argument(
        "--output",
        type=Path,
        help="Salva o relatório em UTF-8 no caminho informado.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    initialize_database()
    observations = completed_wave_observations(args.strategy, args.horizon_minutes)
    if len(observations) != args.expected_trades:
        raise SystemExit(
            f"Esperados {args.expected_trades} trades, mas o banco contém "
            f"{len(observations)} para esse recorte."
        )
    simulations = tuple(
        simulate_concurrent_bankroll(
            observations,
            scenario_name=scenario.name,
            starting_balance_usd=100,
            position_pct=scenario.position_pct,
            max_exposure_pct=scenario.max_exposure_pct,
        )
        for scenario in SCENARIOS
    )
    scale_simulations = tuple(
        simulate_concurrent_bankroll(
            observations,
            scenario_name=scenario.name,
            starting_balance_usd=balance,
            position_pct=scenario.position_pct,
            max_exposure_pct=scenario.max_exposure_pct,
        )
        for scenario in SCENARIOS
        for balance in SCALE_BALANCES
    )
    stress_profiles = tuple(
        scenario for scenario in SCENARIOS if scenario.name in {"MODERADO", "MUITO AGRESSIVO"}
    )
    cost_stress_simulations = tuple(
        (
            cost_bps,
            simulate_concurrent_bankroll(
                _apply_extra_cost(observations, cost_bps),
                scenario_name=scenario.name,
                starting_balance_usd=100,
                position_pct=scenario.position_pct,
                max_exposure_pct=scenario.max_exposure_pct,
            ),
        )
        for scenario in stress_profiles
        for cost_bps in EXTRA_ROUND_TRIP_COST_BPS
    )
    report = format_report(simulations, scale_simulations, cost_stress_simulations)
    if args.output:
        args.output.write_text(report + "\n", encoding="utf-8")
        print(f"Relatório UTF-8 salvo em: {args.output.resolve()}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
