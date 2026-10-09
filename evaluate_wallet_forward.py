import argparse
import json
from dataclasses import asdict

from src.database import initialize_database, rows
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_metrics import (
    summarize_forward_wallet_latency,
    summarize_forward_wallet_latency_by_address,
)
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema
from src.wallet_forward_runs import get_wallet_forward_run, latest_wallet_forward_run


def _load_observations(
    address: str | None = None,
    *,
    run=None,
) -> list[WalletActionObservation]:
    ensure_wallet_forward_observation_schema()
    query = """SELECT id, wallet_address, token_mint, side, chain_time, observed_at
        FROM wallet_forward_observations"""
    clauses: list[str] = []
    params: list[object] = []

    if run is not None:
        cohort = tuple(run.cohort)
        placeholders = ",".join("?" for _ in cohort)
        clauses.append("id > ?")
        params.append(run.baseline_observation_id)
        if run.end_observation_id is not None:
            clauses.append("id <= ?")
            params.append(run.end_observation_id)
        clauses.append(f"wallet_address IN ({placeholders})")
        params.extend(cohort)
    if address:
        clauses.append("wallet_address=?")
        params.append(address)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY observed_at, id"
    result = rows(query, tuple(params))
    return [
        WalletActionObservation(
            address=str(item["wallet_address"]),
            token_mint=str(item["token_mint"]),
            side=str(item["side"]),
            chain_time=int(item["chain_time"]),
            observed_at=int(item["observed_at"]),
        )
        for item in result
    ]


def _duration(value: float | None) -> str:
    return "indisponível" if value is None else f"{value:.1f}s"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Avalia latência chain_time→observed_at das observações forward de wallets. "
            "Por padrão usa a Wallet Forward Run COMPLETED mais recente para não misturar coletas."
        )
    )
    parser.add_argument("--address", help="limita a uma wallet dentro do escopo")
    parser.add_argument("--run-key", help="run específica; padrão = COMPLETED mais recente")
    parser.add_argument(
        "--all-history",
        action="store_true",
        help="modo legado explícito: ignora manifests e agrega toda a tabela",
    )
    parser.add_argument("--json", action="store_true", help="emite JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.run_key and args.all_history:
        print("Erro: --run-key e --all-history são mutuamente exclusivos.")
        return 2

    initialize_database()
    run = None
    if not args.all_history:
        run = (
            get_wallet_forward_run(args.run_key)
            if args.run_key
            else latest_wallet_forward_run(completed_only=True)
        )
        if args.run_key and run is None:
            print(f"Erro: run não encontrada: {args.run_key}")
            return 2

    observations = _load_observations(args.address, run=run)
    overall = summarize_forward_wallet_latency(observations)
    by_wallet = summarize_forward_wallet_latency_by_address(observations)

    if args.json:
        print(
            json.dumps(
                {
                    "scope": (
                        {"mode": "RUN_MANIFEST", "run": asdict(run)}
                        if run is not None
                        else {"mode": "ALL_HISTORY"}
                    ),
                    "overall": asdict(overall),
                    "by_wallet": {
                        address: asdict(summary) for address, summary in by_wallet.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Forward Wallet Latency Evaluation v2")
    print("Modo: RESEARCH / READ ONLY — mede observabilidade, não edge.")
    if run is not None:
        print(
            f"Escopo: {run.run_key} | runtime {run.runtime_version} | status {run.status} | "
            f"ids ({run.baseline_observation_id}, {run.end_observation_id}]"
        )
    else:
        print("Escopo: ALL_HISTORY explícito — resultados de runs diferentes podem estar misturados.")
    print(
        f"Observações: {overall.observation_count} | wallets {overall.wallet_count} | "
        f"tokens {overall.token_count} | buys/sells {overall.buy_count}/{overall.sell_count}"
    )
    print(
        f"Lag min/p50/p95/max: {_duration(overall.min_lag_seconds)} / "
        f"{_duration(overall.median_lag_seconds)} / {_duration(overall.p95_lag_seconds)} / "
        f"{_duration(overall.max_lag_seconds)}"
    )
    print(
        "Cobertura por atraso: "
        f"<=15s {overall.within_15s_share_pct:.1f}% | "
        f"<=30s {overall.within_30s_share_pct:.1f}% | "
        f"<=60s {overall.within_60s_share_pct:.1f}% | "
        f"<=120s {overall.within_120s_share_pct:.1f}%"
    )

    if by_wallet:
        print()
        print("POR WALLET")
        for address, summary in by_wallet.items():
            print(
                f"- {address[:12]}… n={summary.observation_count} | "
                f"p50 {_duration(summary.median_lag_seconds)} | "
                f"p95 {_duration(summary.p95_lag_seconds)} | "
                f"<=60s {summary.within_60s_share_pct:.1f}%"
            )

    print()
    print(
        "O lag mede quando nosso polling tomou conhecimento do swap. Para avaliar copyability, "
        "ainda precisamos cruzar esse atraso com route quote, liquidez, slippage, missingness "
        "e resultado futuro."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
