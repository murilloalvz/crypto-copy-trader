import argparse
import json
from dataclasses import asdict

from src.database import initialize_database, rows
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_integrity import summarize_forward_run_integrity
from src.wallet_forward_metrics import summarize_forward_wallet_latency
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema
from src.wallet_forward_readiness import summarize_wallet_forward_replay_readiness
from src.wallet_forward_runs import get_wallet_forward_run, latest_wallet_forward_run
from src.wallet_quote_completeness import summarize_quote_attempt_completeness
from src.wallet_quote_drift import (
    build_wallet_quote_drift_observations,
    load_successful_quote_path_points,
    summarize_wallet_quote_drift,
)
from src.wallet_quote_metrics import summarize_wallet_quote_metrics
from src.wallet_quote_watch import (
    load_forward_buys_after,
    load_successful_quote_keys_by_event,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compara observabilidade/copyability técnica por wallet dentro de uma única run. "
            "Não calcula score ponderado, PnL ou edge."
        )
    )
    parser.add_argument("--run-key", help="run específica; padrão = COMPLETED mais recente")
    parser.add_argument("--baseline-delay-seconds", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    return parser


def _load_actions(run, wallet_address: str) -> list[WalletActionObservation]:
    ensure_wallet_forward_observation_schema()
    query = """SELECT wallet_address, token_mint, side, chain_time, observed_at
        FROM wallet_forward_observations
        WHERE id>? AND wallet_address=?"""
    params: list[object] = [run.baseline_observation_id, wallet_address]
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


def _profile_wallet(run, wallet_address: str, *, baseline_delay_seconds: int) -> dict:
    actions = _load_actions(run, wallet_address)
    buys = load_forward_buys_after(
        run.baseline_observation_id,
        wallet_addresses=[wallet_address],
        through_id=run.end_observation_id,
    )
    event_keys = [item.observation_key for item in buys]
    successful_by_event = load_successful_quote_keys_by_event(event_keys)
    successful_quote_events = sum(bool(successful_by_event.get(key)) for key in event_keys)

    latency = summarize_forward_wallet_latency(actions)
    integrity = summarize_forward_run_integrity(actions, run_started_at=run.started_at)
    completeness = summarize_quote_attempt_completeness(
        buys,
        delays_seconds=run.quote_delays_seconds if run.with_jupiter_quotes else (),
    )
    quote_metrics = summarize_wallet_quote_metrics(
        wallet_addresses=[wallet_address],
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
        successful_attempt_count=completeness.successful_expected_count,
        failed_attempt_count=completeness.failed_expected_count,
        missing_attempt_count=completeness.missing_attempt_count,
        unexpected_attempt_count=completeness.unexpected_attempt_count,
    )

    points = load_successful_quote_path_points(source_event_keys=event_keys)
    drift_observations = build_wallet_quote_drift_observations(
        points,
        baseline_delay_seconds=baseline_delay_seconds,
    )
    drift = summarize_wallet_quote_drift(
        points,
        drift_observations,
        baseline_delay_seconds=baseline_delay_seconds,
    )

    return {
        "wallet_address": wallet_address,
        "latency": asdict(latency),
        "integrity": asdict(integrity),
        "quote_completeness": asdict(completeness),
        "quote_metrics": asdict(quote_metrics),
        "readiness": asdict(readiness),
        "quote_drift": asdict(drift),
    }


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
        print("Nenhuma Wallet Forward Run compatível encontrada.")
        return 0

    profiles = [
        _profile_wallet(
            run,
            wallet,
            baseline_delay_seconds=args.baseline_delay_seconds,
        )
        for wallet in run.cohort
    ]

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_READ_ONLY",
                    "run": asdict(run),
                    "profiles": profiles,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Forward Wallet Technical Profiles v1")
    print("Modo: RESEARCH / READ ONLY — comparação técnica por wallet, sem edge/PnL.")
    print(
        f"Run: {run.run_key} | runtime {run.runtime_version} | "
        f"quote mode {run.quote_mode} | wallets {len(run.cohort)}"
    )

    for profile in profiles:
        latency = profile["latency"]
        completeness = profile["quote_completeness"]
        readiness = profile["readiness"]
        drift = profile["quote_drift"]
        print()
        print("-" * 88)
        print(profile["wallet_address"])
        print("-" * 88)
        print(
            f"ações {latency['observation_count']} | buy/sell "
            f"{latency['buy_count']}/{latency['sell_count']} | tokens {latency['token_count']}"
        )
        print(
            f"source lag p50/p95/max {_fmt_seconds(latency['median_lag_seconds'])} / "
            f"{_fmt_seconds(latency['p95_lag_seconds'])} / {_fmt_seconds(latency['max_lag_seconds'])}"
        )
        print(
            f"readiness {readiness['label']} | BUYs com quote "
            f"{readiness['successful_quote_event_count']}/{readiness['buy_event_count']} "
            f"({readiness['successful_quote_event_share_pct']:.1f}%)"
        )
        print(
            f"probes {completeness['attempted_expected_count']}/"
            f"{completeness['expected_attempt_count']} tentados | "
            f"success/fail {completeness['successful_expected_count']}/"
            f"{completeness['failed_expected_count']} | missing "
            f"{completeness['missing_attempt_count']}"
        )
        print(
            f"quote drift baseline +{drift['baseline_delay_seconds']}s | "
            f"eventos baseline {drift['baseline_event_count']}"
        )
        for item in drift["delays"]:
            print(
                f"  +{item['delay_seconds']}s paired {item['paired_count']}/"
                f"{item['baseline_event_count']} ({item['paired_coverage_pct']:.1f}%) | "
                f"adverse drift med/p95 {_fmt_pct(item['median_adverse_drift_pct'])}/"
                f"{_fmt_pct(item['p95_adverse_drift_pct'])}"
            )

    print()
    print("INTERPRETAÇÃO")
    print("- Este relatório não cria um Copyability Score novo e não ranqueia por PnL.")
    print("- Wallet rápida pode ser tecnicamente incopiável mesmo que historicamente lucrativa.")
    print("- Quote drift positivo em BUY significa que chegar depois encareceu a entrada.")
    print("- Pouca amostra ou missingness devem permanecer visíveis; não complete mentalmente os gaps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
