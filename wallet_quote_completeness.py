import argparse
import json
from dataclasses import asdict

from src.database import initialize_database
from src.wallet_forward_runs import get_wallet_forward_run, latest_wallet_forward_run
from src.wallet_quote_completeness import summarize_quote_attempt_completeness
from src.wallet_quote_watch import load_forward_buys_after


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compara BUYs×delays esperados contra tentativas realmente persistidas. "
            "RESEARCH/READ ONLY; inclui probes nunca iniciados no denominador."
        )
    )
    parser.add_argument("--run-key", help="run específica; padrão = run COMPLETED mais recente")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    initialize_database()
    run = (
        get_wallet_forward_run(args.run_key)
        if args.run_key
        else latest_wallet_forward_run(completed_only=True)
    )
    if run is None:
        print("Nenhuma Wallet Forward Run COMPLETED encontrada.")
        return 0

    buys = load_forward_buys_after(
        run.baseline_observation_id,
        wallet_addresses=list(run.cohort),
        through_id=run.end_observation_id,
    )
    delays = run.quote_delays_seconds if run.with_jupiter_quotes else ()
    summary = summarize_quote_attempt_completeness(buys, delays_seconds=delays)

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_READ_ONLY",
                    "run": asdict(run),
                    "completeness": asdict(summary),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Wallet Quote Completeness v1")
    print("Modo: RESEARCH / READ ONLY — missing probes permanecem no denominador.")
    print(
        f"Run: {run.run_key} | runtime {run.runtime_version} | quote mode {run.quote_mode} | "
        f"BUYs {summary.buy_event_count} | delays {list(delays)}"
    )
    if not run.with_jupiter_quotes:
        print("Esta run não habilitou Jupiter quotes.")
        return 0

    print(
        f"Esperadas {summary.expected_attempt_count} | tentadas {summary.attempted_expected_count} | "
        f"não tentadas {summary.missing_attempt_count} | inesperadas {summary.unexpected_attempt_count}"
    )
    print(
        f"BUYs com todos os delays tentados: {summary.complete_event_count}/{summary.buy_event_count} "
        f"({summary.complete_event_share_pct:.1f}%)"
    )
    for item in summary.delays:
        print(
            f"- +{item.delay_seconds}s: {item.attempted_count}/{item.expected_count} "
            f"({item.attempt_coverage_pct:.1f}%) | missing {item.missing_count}"
        )
    print()
    print("INTERPRETAÇÃO")
    print("- Sucesso HTTP é outra métrica; aqui perguntamos primeiro se o probe sequer foi tentado.")
    print("- Runs legacy podem revelar gaps de intake/drain que a tabela de attempts sozinha esconderia.")
    print("- Missing probe nunca é convertido em sucesso, falha de preço ou fill inventado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
