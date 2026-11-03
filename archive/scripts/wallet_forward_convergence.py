import argparse
import json
from dataclasses import asdict

from src.database import initialize_database
from src.wallet_forward_convergence import (
    build_forward_wallet_convergence_events,
    summarize_forward_wallet_convergence,
)
from src.wallet_forward_runs import get_wallet_forward_run, latest_wallet_forward_run
from src.wallet_quote_metrics import summarize_wallet_quote_metrics
from src.wallet_quote_watch import load_forward_buys_after


def _fmt_seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}s"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Detecta convergência BUY entre wallets observadas na mesma run forward. "
            "RESEARCH/READ ONLY: não cria sinal, score, ordem ou PnL."
        )
    )
    parser.add_argument("--run-key", help="run específica; padrão = run mais recente")
    parser.add_argument("--window-seconds", type=int, default=300)
    parser.add_argument("--min-wallets", type=int, default=2)
    parser.add_argument("--token-cooldown-seconds", type=int, default=1800)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.window_seconds <= 0:
        print("Erro: --window-seconds precisa ser positivo.")
        return 2
    if args.min_wallets < 2:
        print("Erro: --min-wallets precisa ser >= 2.")
        return 2
    if args.token_cooldown_seconds < 0:
        print("Erro: --token-cooldown-seconds precisa ser >= 0.")
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

    convergence = build_forward_wallet_convergence_events(
        buys,
        window_seconds=args.window_seconds,
        min_unique_buy_wallets=args.min_wallets,
        token_cooldown_seconds=args.token_cooldown_seconds,
    )
    summary = summarize_forward_wallet_convergence(buys, convergence)
    trigger_keys = [item.trigger_observation_key for item in convergence]
    quote_metrics = summarize_wallet_quote_metrics(
        wallet_addresses=list(run.cohort),
        source_event_keys=trigger_keys,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_READ_ONLY",
                    "run": asdict(run),
                    "policy": {
                        "window_seconds": args.window_seconds,
                        "min_unique_buy_wallets": args.min_wallets,
                        "token_cooldown_seconds": args.token_cooldown_seconds,
                    },
                    "summary": asdict(summary),
                    "events": [asdict(item) for item in convergence],
                    "trigger_quote_metrics": asdict(quote_metrics),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Wallet Forward Convergence v1")
    print("Modo: RESEARCH / READ ONLY — convergência observada não é edge nem ordem.")
    print(
        f"Run: {run.run_key} | status {run.status} | cohort {len(run.cohort)} wallets | "
        f"janela {args.window_seconds}s | threshold {args.min_wallets} wallets | "
        f"cooldown/token {args.token_cooldown_seconds}s"
    )
    if run.status != "COMPLETED":
        print("ATENÇÃO: run ainda não está COMPLETED; resultado é parcial e não deve ser promovido.")

    print()
    print("OBSERVABILIDADE")
    print(
        f"BUYs {summary.buy_event_count} | wallets com BUY {summary.buy_wallet_count} | "
        f"tokens comprados {summary.buy_token_count} | convergências {summary.convergence_event_count} | "
        f"tokens convergentes {summary.convergence_token_count}"
    )
    print(
        f"span de convergência p50 {_fmt_seconds(summary.median_convergence_span_seconds)} | "
        f"lag chain→detecção do BUY gatilho p50/p95 "
        f"{_fmt_seconds(summary.median_trigger_source_lag_seconds)}/"
        f"{_fmt_seconds(summary.p95_trigger_source_lag_seconds)}"
    )

    print()
    print("EVENTOS")
    if not convergence:
        print("Nenhuma convergência atingiu o threshold nesta run.")
    for item in convergence:
        wallets = ", ".join(address[:10] + "…" for address in item.participating_wallets)
        print(
            f"- {item.token_mint} | t={item.triggered_at} | {item.unique_buy_wallet_count} wallets | "
            f"span {item.convergence_span_seconds}s | trigger lag {item.trigger_source_lag_seconds}s"
        )
        print(f"  wallets: {wallets}")
        print(f"  trigger event: {item.trigger_observation_key}")

    print()
    print("JUPITER NO BUY QUE FECHOU A CONVERGÊNCIA")
    if not run.with_jupiter_quotes:
        print("Esta run não coletou Jupiter quotes.")
    elif not convergence:
        print("Sem evento de convergência, portanto sem trigger quote para auditar.")
    else:
        print(
            f"tentativas {quote_metrics.attempt_count} | sucesso {quote_metrics.success_count} "
            f"({quote_metrics.success_pct:.1f}%) | falhas {quote_metrics.failure_count} | "
            f"proxy {quote_metrics.proxy_count} | tx candidata {quote_metrics.executable_count}"
        )
        for item in quote_metrics.delays:
            print(
                f"- +{item.delay_seconds}s: {item.success_count}/{item.attempt_count} "
                f"({item.success_pct:.1f}%) | request lag p50/p95 "
                f"{_fmt_seconds(item.median_request_lag_seconds)}/"
                f"{_fmt_seconds(item.p95_request_lag_seconds)}"
            )

    print()
    print("INTERPRETAÇÃO")
    print("- O evento usa observed_at; uma wallet sincronizada depois não confirma o passado.")
    print("- Só a chegada de uma nova wallet única pode cruzar o threshold.")
    print("- Cooldown por token evita contar repetidamente o mesmo burst como amostras independentes.")
    print("- Convergência entre wallets monitoradas não prova que elas têm informação especial.")
    print("- O próximo teste causal continua sendo target vs controles placebo pré-período.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
