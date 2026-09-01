import argparse
import json
from dataclasses import asdict

from src.database import initialize_database, rows
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_integrity import summarize_forward_run_integrity
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema
from src.wallet_forward_readiness import summarize_wallet_forward_replay_readiness
from src.wallet_forward_runs import get_wallet_forward_run, latest_wallet_forward_run
from src.wallet_quote_completeness import summarize_quote_attempt_completeness
from src.wallet_quote_metrics import summarize_wallet_quote_metrics
from src.wallet_quote_watch import (
    load_forward_buys_after,
    load_successful_quote_keys_by_event,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Classifica a prontidão de dados de uma Wallet Forward Run para causal replay "
            "descritivo. Não mede edge, PnL e nunca autoriza shadow/live."
        )
    )
    parser.add_argument("--run-key", help="run específica; padrão = COMPLETED mais recente")
    parser.add_argument("--json", action="store_true")
    return parser


def _load_actions(run) -> list[WalletActionObservation]:
    ensure_wallet_forward_observation_schema()
    addresses = tuple(run.cohort)
    placeholders = ",".join("?" for _ in addresses)
    query = f"""SELECT wallet_address, token_mint, side, chain_time, observed_at
        FROM wallet_forward_observations
        WHERE id>? AND wallet_address IN ({placeholders})"""
    params: list[object] = [run.baseline_observation_id, *addresses]
    if run.end_observation_id is not None:
        query += " AND id<=?"
        params.append(run.end_observation_id)
    query += " ORDER BY observed_at, id"
    return [
        WalletActionObservation(
            address=str(item["wallet_address"]),
            token_mint=str(item["token_mint"]),
            side=str(item["side"]),
            chain_time=int(item["chain_time"]),
            observed_at=int(item["observed_at"]),
        )
        for item in rows(query, tuple(params))
    ]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    initialize_database()
    run = (
        get_wallet_forward_run(args.run_key)
        if args.run_key
        else latest_wallet_forward_run(completed_only=True)
    )
    if run is None:
        print("Nenhuma Wallet Forward Run compatível encontrada.")
        return 0

    actions = _load_actions(run)
    buys = load_forward_buys_after(
        run.baseline_observation_id,
        wallet_addresses=list(run.cohort),
        through_id=run.end_observation_id,
    )
    event_keys = [item.observation_key for item in buys]
    successful_keys = load_successful_quote_keys_by_event(event_keys)
    successful_quote_events = sum(bool(successful_keys.get(key)) for key in event_keys)

    integrity = summarize_forward_run_integrity(actions, run_started_at=run.started_at)
    completeness = summarize_quote_attempt_completeness(
        buys,
        delays_seconds=run.quote_delays_seconds if run.with_jupiter_quotes else (),
    )
    quote_metrics = summarize_wallet_quote_metrics(
        wallet_addresses=list(run.cohort),
        source_event_keys=event_keys,
    )
    readiness = summarize_wallet_forward_replay_readiness(
        run_status=run.status,
        runtime_version=run.runtime_version,
        quote_mode=run.quote_mode,
        with_jupiter_quotes=run.with_jupiter_quotes,
        integrity_label=integrity.integrity_label,
        action_count=len(actions),
        buy_event_count=len(buys),
        successful_quote_event_count=successful_quote_events,
        expected_attempt_count=completeness.expected_attempt_count,
        attempted_expected_count=completeness.attempted_expected_count,
        successful_attempt_count=quote_metrics.success_count,
        failed_attempt_count=quote_metrics.failure_count,
        missing_attempt_count=completeness.missing_attempt_count,
        unexpected_attempt_count=completeness.unexpected_attempt_count,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_READ_ONLY",
                    "run": asdict(run),
                    "integrity": asdict(integrity),
                    "quote_completeness": asdict(completeness),
                    "quote_metrics": asdict(quote_metrics),
                    "readiness": asdict(readiness),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Wallet Forward Replay Readiness v1")
    print("Modo: RESEARCH / READ ONLY — gate de dados, NÃO gate de edge/live.")
    print(
        f"Run: {run.run_key} | runtime {run.runtime_version} | status {run.status} | "
        f"quote mode {run.quote_mode}"
    )
    print(f"READINESS: {readiness.label}")
    print(
        f"Ações {readiness.action_count} | BUYs {readiness.buy_event_count} | "
        f"BUYs com >=1 quote de sucesso {readiness.successful_quote_event_count}/"
        f"{readiness.buy_event_count} ({readiness.successful_quote_event_share_pct:.1f}%)"
    )
    print(
        f"Probes esperados/tentados {readiness.expected_attempt_count}/"
        f"{readiness.attempted_expected_count} ({readiness.attempt_coverage_pct:.1f}%) | "
        f"sucesso/falha {readiness.successful_attempt_count}/{readiness.failed_attempt_count} | "
        f"sucesso entre tentados {readiness.attempt_success_pct:.1f}%"
    )
    print(
        f"Causal integrity: {integrity.integrity_label} | "
        f"replay descritivo {'LIBERADO' if readiness.descriptive_replay_allowed else 'BLOQUEADO'} | "
        "promoção econômica BLOQUEADA"
    )

    if readiness.blockers:
        print("\nBLOCKERS")
        for item in readiness.blockers:
            print(f"- {item}")
    if readiness.cautions:
        print("\nCAUTIONS")
        for item in readiness.cautions:
            print(f"- {item}")

    print("\nPRÓXIMOS PASSOS")
    for item in readiness.next_steps:
        print(f"- {item}")

    print()
    print(
        "Interpretação: CAUSAL_REPLAY_SAMPLE_READY significa apenas que o caminho de dados "
        "da run está completo o suficiente para replay descritivo. Não significa estratégia "
        "lucrativa, wallet copiável, shadow aprovado ou live aprovado."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
