import argparse
import json
from dataclasses import asdict

from src.database import initialize_database
from src.wallet_forward_runs import get_wallet_forward_run, latest_wallet_forward_run
from src.wallet_quote_drift import (
    build_wallet_quote_drift_observations,
    load_successful_quote_path_points,
    summarize_wallet_quote_drift,
)
from src.wallet_quote_metrics import summarize_wallet_quote_metrics
from src.wallet_quote_watch import load_forward_buys_after


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def _fmt_seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}s"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compara o preço das route quotes do MESMO evento forward entre delays. "
            "RESEARCH/READ ONLY: mede drift de execução, não retorno do token."
        )
    )
    parser.add_argument("--run-key", help="run específica; padrão = run mais recente")
    parser.add_argument("--baseline-delay-seconds", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.baseline_delay_seconds < 0:
        print("Erro: --baseline-delay-seconds precisa ser >= 0.")
        return 2

    initialize_database()
    run = (
        get_wallet_forward_run(args.run_key)
        if args.run_key
        else latest_wallet_forward_run(completed_only=False)
    )
    if run is None:
        print("Nenhuma wallet forward run encontrada.")
        return 0

    buys = load_forward_buys_after(
        run.baseline_observation_id,
        wallet_addresses=list(run.cohort),
    )
    if run.end_observation_id is not None:
        buys = [item for item in buys if item.id <= run.end_observation_id]
    event_keys = [item.observation_key for item in buys]

    points = load_successful_quote_path_points(source_event_keys=event_keys)
    drift = build_wallet_quote_drift_observations(
        points,
        baseline_delay_seconds=args.baseline_delay_seconds,
    )
    summary = summarize_wallet_quote_drift(
        points,
        drift,
        baseline_delay_seconds=args.baseline_delay_seconds,
    )
    attempts = summarize_wallet_quote_metrics(
        wallet_addresses=list(run.cohort),
        source_event_keys=event_keys,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_READ_ONLY",
                    "run": asdict(run),
                    "buy_event_count": len(buys),
                    "quote_attempt_metrics": asdict(attempts),
                    "drift_summary": asdict(summary),
                    "drift_observations": [asdict(item) for item in drift],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Wallet Quote Drift v1")
    print("Modo: RESEARCH / READ ONLY — drift de route price, não PnL/edge.")
    print(
        f"Run: {run.run_key} | status {run.status} | BUYs {len(buys)} | "
        f"baseline +{args.baseline_delay_seconds}s"
    )
    if run.status != "COMPLETED":
        print("ATENÇÃO: run ainda está parcial; não use o resultado como checkpoint final.")
    if not run.with_jupiter_quotes:
        print("Esta run não habilitou Jupiter quotes; não há drift de rota para avaliar.")
        return 0

    print()
    print("COBERTURA DE QUOTES")
    print(
        f"tentativas {attempts.attempt_count} | sucesso {attempts.success_count} "
        f"({attempts.success_pct:.1f}%) | falhas {attempts.failure_count} | "
        f"proxy {attempts.proxy_count} | tx candidata {attempts.executable_count}"
    )

    print()
    print("DRIFT PAREADO VS BASELINE DO MESMO BUY")
    print(
        f"eventos com baseline bem-sucedida: {summary.baseline_event_count} | "
        f"wallets {summary.wallet_count} | tokens {summary.token_count}"
    )
    if summary.baseline_event_count == 0:
        print("Sem baseline pareável; não estimamos drift usando outro evento/token.")
    for item in summary.delays:
        print(
            f"- +{item.delay_seconds}s: pareados {item.paired_count}/{item.baseline_event_count} "
            f"({item.paired_coverage_pct:.1f}%) | adverse drift p50/p95 "
            f"{_fmt_pct(item.median_adverse_drift_pct)}/{_fmt_pct(item.p95_adverse_drift_pct)} | "
            f"melhor/pior {_fmt_pct(item.best_adverse_drift_pct)}/"
            f"{_fmt_pct(item.worst_adverse_drift_pct)}"
        )
        print(
            f"  request atraso vs target p50 {_fmt_seconds(item.median_target_request_lag_seconds)} | "
            f"wallet→quote p50 {_fmt_seconds(item.median_wallet_to_quote_seconds)} | "
            f"route change {('n/a' if item.route_change_share_pct is None else f'{item.route_change_share_pct:.1f}%')}"
        )

    print()
    print("INTERPRETAÇÃO")
    print("- Drift positivo = pior preço para o copiador: BUY mais caro / SELL mais barato.")
    print("- Cada comparação usa o MESMO evento; não mistura tokens ou ações diferentes.")
    print("- Eventos sem quote baseline continuam fora do par e a cobertura permanece explícita.")
    print("- Isto mede custo temporal de rota, não retorno futuro nem lucratividade da wallet.")
    print("- Quote-only não é fill; tx candidata montada também não prova execução on-chain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
