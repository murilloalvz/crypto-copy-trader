import argparse
import json
from dataclasses import asdict

from src.database import initialize_database
from src.wallet_entry_latency import summarize_wallet_entry_latency
from src.wallet_forward_dependence import summarize_wallet_forward_dependence
from src.wallet_forward_runs import get_wallet_forward_run, latest_wallet_forward_run
from src.wallet_quote_drift import (
    build_wallet_quote_drift_observations,
    load_successful_quote_path_points,
)
from src.wallet_quote_watch import load_forward_buys_after


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audita latência end-to-end e dependência/repetição dos BUYs de uma Wallet Forward "
            "Run. RESEARCH/READ ONLY; não mede PnL nem edge."
        )
    )
    parser.add_argument("--run-key", help="run específica; padrão = COMPLETED mais recente")
    parser.add_argument("--baseline-delay-seconds", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    return parser


def _fmt_seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}s"


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.baseline_delay_seconds < 0:
        print("Erro: --baseline-delay-seconds precisa ser >= 0.")
        return 2

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
    event_keys = [item.observation_key for item in buys]
    points = load_successful_quote_path_points(source_event_keys=event_keys)
    drift = build_wallet_quote_drift_observations(
        points,
        baseline_delay_seconds=args.baseline_delay_seconds,
    )
    latency = summarize_wallet_entry_latency(points, buy_event_count=len(buys))
    dependence = summarize_wallet_forward_dependence(buys, drift_observations=drift)

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_READ_ONLY",
                    "run": asdict(run),
                    "entry_latency": asdict(latency),
                    "sample_dependence": asdict(dependence),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Wallet Forward Sample Quality v1")
    print("Modo: RESEARCH / READ ONLY — latência/dependência, não PnL/edge.")
    print(
        f"Run: {run.run_key} | runtime {run.runtime_version} | BUYs {len(buys)} | "
        f"quote mode {run.quote_mode}"
    )

    print()
    print("1. END-TO-END ENTRY LATENCY")
    print(
        "Delay +Xs = atraso configurado DEPOIS que o nosso coletor detectou o swap. "
        "O tempo real desde a ação on-chain é chain→detecção + delay + scheduler/HTTP."
    )
    if not latency.delays:
        print("Sem quotes de sucesso para medir latência end-to-end.")
    for item in latency.delays:
        print(
            f"- delay após detecção +{item.delay_seconds}s | quotes "
            f"{item.quoted_event_count}/{item.buy_event_count} ({item.coverage_pct:.1f}%) | "
            f"chain→detecção med {_fmt_seconds(item.median_chain_to_detection_seconds)} | "
            f"detecção→quote med {_fmt_seconds(item.median_detection_to_quote_seconds)} | "
            f"chain→quote med/p95 {_fmt_seconds(item.median_chain_to_quote_seconds)}/"
            f"{_fmt_seconds(item.p95_chain_to_quote_seconds)}"
        )
        print(
            f"  chain→quote <=30s {item.within_30s_share_pct:.1f}% | "
            f"<=60s {item.within_60s_share_pct:.1f}% | <=120s {item.within_120s_share_pct:.1f}%"
        )

    print()
    print("2. SAMPLE DEPENDENCE / REPEATED BUYS")
    print(
        f"BUY events {dependence.buy_event_count} | wallets {dependence.wallet_count} | "
        f"tokens {dependence.token_count} | wallet×token clusters "
        f"{dependence.wallet_token_cluster_count}"
    )
    print(
        f"BUYs repetidos no mesmo wallet×token: {dependence.repeated_wallet_token_buy_count}/"
        f"{dependence.buy_event_count} ({dependence.repeated_wallet_token_buy_share_pct:.1f}%)"
    )
    print(
        f"Maior wallet: {dependence.largest_wallet_buy_count}/{dependence.buy_event_count} "
        f"({dependence.largest_wallet_buy_share_pct:.1f}%) | maior token: "
        f"{dependence.largest_token_buy_count}/{dependence.buy_event_count} "
        f"({dependence.largest_token_buy_share_pct:.1f}%) | maior wallet×token cluster: "
        f"{dependence.largest_wallet_token_cluster_count}/{dependence.buy_event_count} "
        f"({dependence.largest_wallet_token_cluster_share_pct:.1f}%)"
    )
    if dependence.cautions:
        print("CAUTIONS: " + ", ".join(dependence.cautions))

    if dependence.drift_clusters:
        print()
        print("3. QUOTE DRIFT — EVENT LEVEL VS TOKEN-CLUSTERED")
        print(
            "Token-clustered = primeiro calcula a mediana dos eventos de cada token e depois "
            "dá peso igual a cada token. Isso reduz a falsa impressão de n grande quando uma "
            "wallet repete muitos BUYs nos mesmos poucos tokens."
        )
        for item in dependence.drift_clusters:
            print(
                f"- +{item.delay_seconds}s | eventos {item.event_count} | tokens "
                f"{item.token_cluster_count} | mediana event-level "
                f"{_fmt_pct(item.event_median_adverse_drift_pct)} | mediana dos tokens "
                f"{_fmt_pct(item.median_of_token_medians_pct)} | faixa das medianas por token "
                f"{_fmt_pct(item.min_token_median_pct)} a {_fmt_pct(item.max_token_median_pct)}"
            )

    print()
    print("INTERPRETAÇÃO")
    print("- +0s NÃO significa zero segundos após o swap da wallet; significa zero delay após detecção.")
    print("- Repeated BUYs são eventos operacionais reais, mas não viram oportunidades independentes.")
    print("- Com poucos tokens, p50/p95 event-level podem parecer mais robustos do que a amostra é.")
    print("- Quote-only continua sendo proxy causal de rota; não prova fill, PnL ou copyability.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
