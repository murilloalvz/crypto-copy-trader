import argparse
import sys

from src.database import initialize_database
from src.prices import GeckoTerminalPriceProvider
from src.rejection_intelligence import (
    latest_rejection_run_id,
    select_rejection_followups,
    settle_due_rejection_followups,
    summarize_rejection_lab,
)
from src.wave_radar import RADAR_BARRIER_LABELS


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audita tokens rejeitados pelo Wave sem alterar os filtros. "
            "RESEARCH/READ ONLY: acompanha contrafactuais de rejeição."
        )
    )
    parser.add_argument(
        "--run-id",
        type=int,
        help="wave_discovery_runs.id; padrão = última run com rejeições",
    )
    parser.add_argument(
        "--select-limit",
        type=int,
        default=12,
        help="máximo de rejeições acompanhadas por run",
    )
    parser.add_argument(
        "--settle",
        action="store_true",
        help="consulta preços já vencidos via GeckoTerminal; sem esta flag não faz rede",
    )
    parser.add_argument(
        "--max-checks",
        type=int,
        default=12,
        help="máximo de horizontes consultados nesta execução",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.run_id is not None and args.run_id <= 0:
        print("Erro: --run-id precisa ser positivo.", file=sys.stderr)
        return 2
    if args.select_limit <= 0 or args.max_checks <= 0:
        print(
            "Erro: --select-limit e --max-checks precisam ser positivos.",
            file=sys.stderr,
        )
        return 2

    initialize_database()
    run_id = args.run_id or latest_rejection_run_id()
    if run_id is None:
        print(
            "Nenhuma rejeição persistida ainda. Rode uma nova discovery quando a fonte "
            "estiver disponível."
        )
        return 0

    selection = select_rejection_followups(run_id, max_tokens=args.select_limit)
    settlement = None
    if args.settle:
        settlement = settle_due_rejection_followups(
            GeckoTerminalPriceProvider(),
            run_id=run_id,
            max_checks=args.max_checks,
        )
    summary = summarize_rejection_lab(run_id)

    print("Crypto Copy Trader — Rejection Intelligence v1")
    print("Modo: RESEARCH / READ ONLY — rejeição observada não vira sinal de compra.")
    print(f"Discovery run_id: {run_id}")
    print(
        f"Rejeições: {summary.rejection_count} | dados válidos: {summary.data_valid_count} | "
        f"barreira única: {summary.single_barrier_count} | acompanhadas: {summary.selected_count}"
    )
    print(
        f"Seleção: disponíveis {selection.available_count} | "
        f"já selecionadas {selection.already_selected_count} | "
        f"novas {selection.newly_selected_count} | total {selection.selected_total}"
    )
    if settlement is not None:
        print(
            f"Settlement: tentados {settlement.attempted} | completos {settlement.completed} | "
            f"falhos {settlement.failed} | adiados temporariamente {settlement.deferred}"
        )

    print("\nHORIZONTES")
    if not summary.horizons:
        print("Nenhum follow-up agendado.")
    for item in summary.horizons:
        positive = item.positive_share_pct if item.positive_share_pct is not None else 0.0
        rally20 = item.rally_20_share_pct if item.rally_20_share_pct is not None else 0.0
        crash25 = item.crash_25_share_pct if item.crash_25_share_pct is not None else 0.0
        print(
            f"- {item.horizon_minutes}m: {item.completed_count}/{item.selected_count} completos "
            f"({item.coverage_pct:.1f}%) | pendentes {item.pending_count} | falhos {item.failed_count} | "
            f"média/mediana {_fmt(item.mean_return_pct)} / {_fmt(item.median_return_pct)} | "
            f">0 {positive:.1f}% | >=+20 {rally20:.1f}% | <=-25 {crash25:.1f}%"
        )

    print("\nBARREIRAS DA RUN")
    for barrier, count in summary.rejection_counts_by_barrier:
        print(f"- {RADAR_BARRIER_LABELS.get(barrier, barrier)}: {count}")

    print("\nINTERPRETAÇÃO")
    print("- +20% e -25% são cortes descritivos do relatório, não novos gates da estratégia.")
    print("- Barreira única é priorizada porque isola melhor o filtro que rejeitou o token.")
    print("- Resultado positivo após rejeição não prova que o filtro é ruim; precisamos de amostra e missingness.")
    print("- Este laboratório não altera wave_v3_volume_integrity e não cria ordens.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
