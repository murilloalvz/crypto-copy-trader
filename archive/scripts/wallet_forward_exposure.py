import argparse
import json
from dataclasses import asdict

from src.database import initialize_database
from src.wallet_forward_exposure import summarize_wallet_forward_exposure
from src.wallet_forward_runs import get_wallet_forward_run, latest_wallet_forward_run
from src.wallet_quote_watch import load_forward_buys_after


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audita quanto follow-up cada BUY forward teve antes do fim da run. "
            "Ajuda a evitar interpretar right-censoring como comportamento de holding."
        )
    )
    parser.add_argument("--run-key", help="run específica; padrão = COMPLETED mais recente")
    parser.add_argument(
        "--horizons-seconds",
        type=int,
        nargs="+",
        default=[900, 3600, 21600, 86400],
        help="horizontes de follow-up (padrão: 15m, 1h, 6h, 24h)",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def _fmt(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    seconds = float(value)
    if seconds >= 3600:
        return f"{seconds / 3600:.2f}h"
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.0f}s"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.horizons_seconds or any(item <= 0 for item in args.horizons_seconds):
        print("Erro: --horizons-seconds precisa conter valores positivos.")
        return 2

    initialize_database()
    run = (
        get_wallet_forward_run(args.run_key)
        if args.run_key
        else latest_wallet_forward_run(completed_only=True)
    )
    if run is None:
        print("Nenhuma Wallet Forward Run compatível encontrada.")
        return 0
    if run.ended_at is None:
        print(f"Erro: run {run.run_key} ainda não possui ended_at.")
        return 2

    all_buys = load_forward_buys_after(
        run.baseline_observation_id,
        wallet_addresses=list(run.cohort),
        through_id=run.end_observation_id,
    )
    overall = summarize_wallet_forward_exposure(
        all_buys,
        observation_window_end_at=run.ended_at,
        horizons_seconds=args.horizons_seconds,
    )
    by_wallet = {}
    for wallet in run.cohort:
        wallet_buys = [item for item in all_buys if item.wallet_address == wallet]
        by_wallet[wallet] = summarize_wallet_forward_exposure(
            wallet_buys,
            observation_window_end_at=run.ended_at,
            horizons_seconds=args.horizons_seconds,
        )

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_READ_ONLY",
                    "run": asdict(run),
                    "overall": asdict(overall),
                    "by_wallet": {key: asdict(value) for key, value in by_wallet.items()},
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Forward Observation Exposure v1")
    print("Modo: RESEARCH / READ ONLY — auditoria de censoring, não edge/PnL.")
    print(f"Run: {run.run_key} | BUYs {overall.buy_count}")
    print(
        "Follow-up restante por BUY p10/med/min/max: "
        f"{_fmt(overall.p10_remaining_observation_seconds)} / "
        f"{_fmt(overall.median_remaining_observation_seconds)} / "
        f"{_fmt(overall.min_remaining_observation_seconds)} / "
        f"{_fmt(overall.max_remaining_observation_seconds)}"
    )
    print("\nELIGIBILIDADE DE FOLLOW-UP")
    for row in overall.horizons:
        print(
            f"- {_fmt(row.horizon_seconds)}: {row.eligible_buy_count}/{overall.buy_count} "
            f"({row.eligible_share_pct:.1f}%) tiveram a janela completa dentro da run"
        )

    print("\nPOR WALLET")
    for wallet, summary in by_wallet.items():
        print(
            f"- {wallet[:12]}… BUYs={summary.buy_count} | "
            f"follow-up mediano={_fmt(summary.median_remaining_observation_seconds)}"
        )
        for row in summary.horizons:
            print(
                f"  {_fmt(row.horizon_seconds)}: {row.eligible_buy_count}/{summary.buy_count} "
                f"({row.eligible_share_pct:.1f}%)"
            )

    print("\nINTERPRETAÇÃO")
    print("- Right-censoring = a run termina antes de sabermos como aquela posição evoluiria.")
    print("- BUY sem SELL antes do fim não prova hold longo se faltou follow-up suficiente.")
    print("- Para H1 de 7mPti (>6h até primeiro exit), BUY precisa de >=6h de exposição para sequer testar a fronteira.")
    print("- H2/H3 com fronteira <15m precisam ao menos >=15m de exposição, mas reentry/multi-sell ainda exigem política de follow-up própria antes de pass/fail.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
