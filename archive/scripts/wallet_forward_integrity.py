import argparse
import json
from dataclasses import asdict

from src.database import initialize_database, rows
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_forward_integrity import summarize_forward_run_integrity
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema
from src.wallet_forward_runs import get_wallet_forward_run, latest_wallet_forward_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audita causalidade/lag de uma Wallet Forward Run sem alterar dados. "
            "RESEARCH/READ ONLY."
        )
    )
    parser.add_argument("--run-key", help="run específica; padrão = run COMPLETED mais recente")
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
    summary = summarize_forward_run_integrity(actions, run_started_at=run.started_at)

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "RESEARCH_READ_ONLY",
                    "run": asdict(run),
                    "integrity": asdict(summary),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Crypto Copy Trader — Wallet Forward Integrity v1")
    print("Modo: RESEARCH / READ ONLY — auditoria; nenhuma linha é apagada ou reclassificada.")
    print(f"Run: {run.run_key} | status {run.status} | actions {summary.action_count}")
    print(f"Gate: {summary.integrity_label}")
    print(
        f"observed_at antes da run: {summary.observed_before_run_count} | "
        f"chain_time antes da run: {summary.chain_before_run_count} | "
        f"lag negativo: {summary.negative_source_lag_count}"
    )
    print(
        f"source lag >5m: {summary.source_lag_over_300s_count} "
        f"({summary.source_lag_over_300s_share_pct:.1f}%) | "
        f">1h: {summary.source_lag_over_3600s_count}"
    )
    print(
        "lag p50/p95/max: "
        f"{summary.median_source_lag_seconds if summary.median_source_lag_seconds is not None else 'n/a'} / "
        f"{summary.p95_source_lag_seconds if summary.p95_source_lag_seconds is not None else 'n/a'} / "
        f"{summary.max_source_lag_seconds if summary.max_source_lag_seconds is not None else 'n/a'} s"
    )
    print()
    print("INTERPRETAÇÃO")
    print("- A auditoria não remove observações suspeitas: ela mantém a contaminação visível.")
    print("- chain_time pré-run por poucos segundos pode ser atraso de observação; lag grande é mais preocupante.")
    print("- O collector v2 bloqueia prospectivamente transações com chain_time anterior à fronteira causal.")
    print("- Runs antigas continuam auditáveis e não são reescritas retroativamente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
